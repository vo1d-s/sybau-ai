from core import api
from extra import ui, tool_parser
from tools import executor

# actual generate handler
async def _stream(user_message: str, model_id: str, system_prompt: str, memory: list):
    # accumulate to send at the end

    ui.print_model_name(model_id)

    full = ""
    
    async for chunk in api.stream_chat(user_message, model_id, system_prompt, memory):
        # print delta, ai message
        delta = chunk.get("delta")
        if delta:
            full += delta
            print(delta, end="")

        # detect if done
        if chunk.get("done"):
            memory.append({
                "role": "assistant",
                "content": full
            })

            print("\n")
            return full, memory

# checks for cutoffs on the response
async def _stream_agent(user_message: str, model_id: str, system_prompt: str, memory: list):
    # generates full response
    full, saved_memory = await _stream(
        user_message, 
        model_id, 
        system_prompt, 
        memory
    )

    # TODO: detect and prevent cut offs

    return full, saved_memory

# parses tools found on the response
async def run_agent(user_message: str, model_id: str, system_prompt: str, memory: list):
    # stream the response

    response, saved_memory = await _stream_agent(
        user_message,
        model_id,
        system_prompt,
        memory
    )

    while True:
        # extract tools in the response
        tools, tool_errors = tool_parser.extract_tools_with_errors(response)

        if tools:
            # print all tool names
            names = ", ".join(t.get("name", "?") for t in tools)
            ui.print_tools(names)

            # if multiple found, run all
            results = await executor.run_tools_parallel(tools)

            tool_text = "\n".join(str(r) for r in results)

            # send tool results back to model
            response, saved_memory = await _stream_agent(
                f"Tool results:\n{tool_text}",
                model_id,
                system_prompt,
                saved_memory
            )

            continue

        return response, saved_memory