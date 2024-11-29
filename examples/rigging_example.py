import asyncio
import requests
import rigging as rg
from rigging import logging, logger
from rich import print

logger.enable("rigging")

try:
    target = input("Enter the target IP address or domain: ").strip()
    if not target:  # Check for empty string
        target = "127.0.0.1"
        logger.info(f"Defaulting to target: {target}")
except Exception as e:
    logger.error(f"Error reading input: {e}")
    target = "127.0.0.1"
    logger.info(f"Falling back to default target: {target}")

# we need to wrap the tools in a class that Rigging can understand


class Wrapper(rg.Tool):
    # we'll set these in the constructor
    name = "_"
    description = "_"

    def __init__(self, tool: dict):
        self.tool = tool
        self.name = tool["name"]
        self.description = tool["description"]

        # declare dynamically the functions by their name
        for function in tool["functions"]:
            setattr(
                Wrapper,
                function["name"],
                lambda self, *args, **kwargs: self._execute_function(
                    function["name"], *args, **kwargs
                ),
            )

    def _execute_function(self, func_name: str, *args, **kwargs):
        print(f"executing {self.name}.{func_name}{kwargs} ...")
        # execute the call via robopages and return the result to Rigging
        return requests.post(
            "http://localhost:8000/process",
            json=[
                {
                    "type": "function",
                    "function": {
                        "name": func_name,
                        "arguments": kwargs,
                    },
                }
            ],
        ).json()[0]["content"]

    def get_description(self) -> rg.tool.ToolDescription:
        """Creates a full description of the tool for use in prompting"""

        return rg.tool.ToolDescription(
            name=self.name,
            description=self.description,
            functions=[
                rg.tool.ToolFunction(
                    name=function["name"],
                    description=function["description"],
                    parameters=[
                        rg.tool.ToolParameter(
                            name=param["name"],
                            type=param["type"],
                            description=param["description"],
                        )
                        for param in function["parameters"]
                    ],
                )
                for function in self.tool["functions"]
            ],
        )


async def run(model: str):
    # get the tools from the Robopages server and wrap each function for Rigging
    tools = [
        Wrapper(tool)
        for tool in requests.get("http://localhost:8000/?flavor=rigging").json()
    ]

    # First LLM - Command Generator
    command_chat = (
        await rg.get_generator(model)
        .chat(f"Find open ports on \"{target}\" and include all results.")
        .using(*tools, force=True)
        .run()
    )

    command_response = command_chat.last.content
    print("\nCommand Output:", command_response)

    # Second LLM - Security Evaluator
    system_prompt = """You are a penetration testing expert.
    Analyze the output of security commands and provide next steps towards explotation. Start your response with "Evaluation:"
    1. What the results mean
    2. How to exploit them further
    3. Use the available tools to achieve exploitation
    4. If a robopage is not available, provide the relevant terminal/docker command.
    Be concise but thorough."""

    # Include system message as part of the chat prompt
    analysis_prompt = f"""System: {system_prompt}

Command Output to Analyze:
{command_response}

Please provide your analysis:"""

    pentest_evaluator = (
        await rg.get_generator(model)
        .chat(analysis_prompt)
        .using(*tools, force=True)
        .run()
    )

    print("\nSecurity Evaluation:")
    print(pentest_evaluator.last.content)

if __name__ == "__main__":
    asyncio.run(run("gpt-4"))
