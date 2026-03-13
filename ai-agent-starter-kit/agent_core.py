"""
AI Agent Core — Production-ready autonomous agent engine.
Part of the AI Agent Starter Kit.
Buy the full kit at: https://godlymane.gumroad.com
"""

import json
import time
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    """Configuration for an AI Agent."""
    name: str
    model: str = "claude-3-5-sonnet-20241022"
    max_steps: int = 50
    max_cost_usd: float = 10.0
    temperature: float = 0.7
    system_prompt: str = ""
    memory_enabled: bool = True
    verbose: bool = False


@dataclass
class ToolResult:
    """Result from a tool execution."""
    tool_name: str
    success: bool
    output: Any
    error: Optional[str] = None
    duration_ms: float = 0.0
    cost_usd: float = 0.0


@dataclass
class AgentStep:
    """A single step in the agent's reasoning chain."""
    step_num: int
    thought: str
    action: str
    action_input: Dict[str, Any]
    observation: str
    timestamp: datetime = field(default_factory=datetime.now)
    cost_usd: float = 0.0


@dataclass 
class AgentResult:
    """Final result of an agent run."""
    success: bool
    output: str
    steps: List[AgentStep]
    total_cost_usd: float
    total_tokens: int
    duration_seconds: float
    error: Optional[str] = None


class ToolRegistry:
    """Registry for agent tools."""
    
    def __init__(self):
        self._tools: Dict[str, Callable] = {}
        self._tool_schemas: Dict[str, Dict] = {}
    
    def register(self, name: str, func: Callable, schema: Dict):
        """Register a new tool."""
        self._tools[name] = func
        self._tool_schemas[name] = schema
        logger.info(f"Registered tool: {name}")
    
    def get_tool(self, name: str) -> Optional[Callable]:
        return self._tools.get(name)
    
    def get_schemas(self) -> List[Dict]:
        return list(self._tool_schemas.values())
    
    def execute(self, tool_name: str, **kwargs) -> ToolResult:
        """Execute a tool by name."""
        if tool_name not in self._tools:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                output=None,
                error=f"Tool '{tool_name}' not found. Available tools: {list(self._tools.keys())}"
            )
        
        start = time.time()
        try:
            result = self._tools[tool_name](**kwargs)
            return ToolResult(
                tool_name=tool_name,
                success=True,
                output=result,
                duration_ms=(time.time() - start) * 1000
            )
        except Exception as e:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                output=None,
                error=str(e),
                duration_ms=(time.time() - start) * 1000
            )


class Agent:
    """
    Production-grade autonomous AI agent.
    
    Usage:
        agent = Agent(
            name="researcher",
            tools=[web_search, read_url, summarize],
            max_steps=20,
            max_cost_usd=2.0
        )
        result = agent.run("Research the top 5 AI agent frameworks in 2025")
    """
    
    def __init__(
        self,
        name: str,
        model: str = "claude-3-5-sonnet-20241022",
        tools: Optional[List] = None,
        memory: bool = True,
        max_steps: int = 50,
        max_cost: float = 10.0,
        system_prompt: str = "",
        verbose: bool = False
    ):
        self.config = AgentConfig(
            name=name,
            model=model,
            max_steps=max_steps,
            max_cost_usd=max_cost,
            memory_enabled=memory,
            system_prompt=system_prompt,
            verbose=verbose
        )
        self.registry = ToolRegistry()
        self.steps: List[AgentStep] = []
        self.total_cost = 0.0
        self.total_tokens = 0
        
        # Register provided tools
        if tools:
            for tool in tools:
                if hasattr(tool, '__agent_tool__'):
                    self.registry.register(
                        tool.__agent_tool__['name'],
                        tool,
                        tool.__agent_tool__['schema']
                    )
        
        logger.info(f"Agent '{name}' initialized with model={model}, max_steps={max_steps}")
    
    def _build_system_prompt(self) -> str:
        """Build the system prompt for the agent."""
        base_prompt = self.config.system_prompt or (
            "You are a helpful autonomous AI agent. You have access to tools to complete tasks. "
            "Think step by step. Use tools when needed. Be concise and focused."
        )
        
        tool_schemas = self.registry.get_schemas()
        if tool_schemas:
            tools_description = "\n\nAvailable tools:\n"
            for schema in tool_schemas:
                tools_description += f"- {schema['name']}: {schema.get('description', '')}\n"
            return base_prompt + tools_description
        
        return base_prompt
    
    def _parse_response(self, response_text: str) -> Tuple[str, Optional[str], Optional[Dict]]:
        """Parse LLM response to extract thought, action, and action input."""
        thought = ""
        action = None
        action_input = {}
        
        lines = response_text.strip().split('\n')
        current_section = None
        action_input_text = ""
        
        for line in lines:
            line = line.strip()
            if line.startswith("Thought:"):
                thought = line[8:].strip()
                current_section = "thought"
            elif line.startswith("Action:"):
                action = line[7:].strip()
                current_section = "action"
            elif line.startswith("Action Input:"):
                action_input_text = line[13:].strip()
                current_section = "action_input"
            elif line.startswith("Final Answer:"):
                return response_text[response_text.find("Final Answer:") + 13:].strip(), None, None
            elif current_section == "action_input":
                action_input_text += " " + line
        
        # Try to parse action input as JSON
        if action_input_text:
            try:
                action_input = json.loads(action_input_text)
            except json.JSONDecodeError:
                action_input = {"input": action_input_text}
        
        return thought, action, action_input
    
    def run(self, task: str) -> AgentResult:
        """
        Run the agent on a task.
        
        Args:
            task: The task for the agent to complete
            
        Returns:
            AgentResult with the final output and execution details
        """
        start_time = time.time()
        self.steps = []
        self.total_cost = 0.0
        
        if self.config.verbose:
            print(f"\n🤖 Agent '{self.config.name}' starting task: {task}\n")
        
        messages = [
            {"role": "user", "content": task}
        ]
        
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        except ImportError:
            return AgentResult(
                success=False,
                output="",
                steps=self.steps,
                total_cost_usd=0.0,
                total_tokens=0,
                duration_seconds=time.time() - start_time,
                error="anthropic package not installed. Run: pip install anthropic"
            )
        
        for step_num in range(self.config.max_steps):
            # Cost guard
            if self.total_cost >= self.config.max_cost_usd:
                break
            
            try:
                response = client.messages.create(
                    model=self.config.model,
                    max_tokens=4096,
                    system=self._build_system_prompt(),
                    messages=messages
                )
                
                response_text = response.content[0].text
                
                # Track tokens and cost (rough estimate)
                input_tokens = response.usage.input_tokens
                output_tokens = response.usage.output_tokens
                self.total_tokens += input_tokens + output_tokens
                # Claude Sonnet pricing: $3/1M input, $15/1M output
                step_cost = (input_tokens * 0.000003) + (output_tokens * 0.000015)
                self.total_cost += step_cost
                
                if self.config.verbose:
                    print(f"Step {step_num + 1}: {response_text[:200]}...")
                
                # Check for final answer
                if "Final Answer:" in response_text:
                    final_answer = response_text[response_text.find("Final Answer:") + 13:].strip()
                    
                    self.steps.append(AgentStep(
                        step_num=step_num + 1,
                        thought="Task complete",
                        action="final_answer",
                        action_input={},
                        observation=final_answer,
                        cost_usd=step_cost
                    ))
                    
                    return AgentResult(
                        success=True,
                        output=final_answer,
                        steps=self.steps,
                        total_cost_usd=self.total_cost,
                        total_tokens=self.total_tokens,
                        duration_seconds=time.time() - start_time
                    )
                
                # Parse thought/action/action_input
                thought, action, action_input = self._parse_response(response_text)
                
                if not action:
                    # No action found — treat full response as final answer
                    return AgentResult(
                        success=True,
                        output=response_text,
                        steps=self.steps,
                        total_cost_usd=self.total_cost,
                        total_tokens=self.total_tokens,
                        duration_seconds=time.time() - start_time
                    )
                
                # Execute tool
                tool_result = self.registry.execute(action, **(action_input or {}))
                observation = str(tool_result.output) if tool_result.success else f"Error: {tool_result.error}"
                
                step = AgentStep(
                    step_num=step_num + 1,
                    thought=thought,
                    action=action,
                    action_input=action_input or {},
                    observation=observation,
                    cost_usd=step_cost
                )
                self.steps.append(step)
                
                if self.config.verbose:
                    print(f"  → Tool: {action}")
                    print(f"  → Result: {observation[:100]}...")
                
                # Add to conversation history
                messages.append({"role": "assistant", "content": response_text})
                messages.append({"role": "user", "content": f"Observation: {observation}"})
                
            except Exception as e:
                logger.error(f"Agent step {step_num + 1} failed: {e}")
                return AgentResult(
                    success=False,
                    output="",
                    steps=self.steps,
                    total_cost_usd=self.total_cost,
                    total_tokens=self.total_tokens,
                    duration_seconds=time.time() - start_time,
                    error=str(e)
                )
        
        return AgentResult(
            success=False,
            output="",
            steps=self.steps,
            total_cost_usd=self.total_cost,
            total_tokens=self.total_tokens,
            duration_seconds=time.time() - start_time,
            error=f"Max steps ({self.config.max_steps}) reached without completing task"
        )
    
    def get_stats(self) -> Dict:
        """Get execution statistics."""
        return {
            "name": self.config.name,
            "steps_taken": len(self.steps),
            "total_cost_usd": round(self.total_cost, 4),
            "total_tokens": self.total_tokens,
            "tools_used": list(set(s.action for s in self.steps if s.action != "final_answer"))
        }


def tool(name: str, description: str, schema: Dict):
    """Decorator to register a function as an agent tool."""
    def decorator(func: Callable):
        func.__agent_tool__ = {
            "name": name,
            "description": description,
            "schema": {
                "name": name,
                "description": description,
                **schema
            }
        }
        return func
    return decorator


# Example tools
@tool(
    name="web_search",
    description="Search the web for information",
    schema={
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"}
            },
            "required": ["query"]
        }
    }
)
def web_search(query: str) -> str:
    """Search the web. In production, use SerpAPI or similar."""
    # Implement with your preferred search API
    return f"[STUB] Search results for: {query}"


@tool(
    name="read_file",
    description="Read contents of a file",
    schema={
        "parameters": {
            "type": "object", 
            "properties": {
                "path": {"type": "string", "description": "File path to read"}
            },
            "required": ["path"]
        }
    }
)
def read_file(path: str) -> str:
    """Read a file from disk."""
    with open(path, 'r') as f:
        return f.read()


@tool(
    name="write_file",
    description="Write content to a file",
    schema={
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["path", "content"]
        }
    }
)
def write_file_tool(path: str, content: str) -> str:
    """Write content to a file."""
    with open(path, 'w') as f:
        f.write(content)
    return f"Written {len(content)} bytes to {path}"


if __name__ == "__main__":
    # Quick demo
    agent = Agent(
        name="demo",
        tools=[web_search, read_file, write_file_tool],
        max_steps=5,
        verbose=True
    )
    
    print("Agent initialized successfully!")
    print(f"Available tools: {list(agent.registry._tools.keys())}")
    print("\nBuy the full kit at: https://godlymane.gumroad.com")
