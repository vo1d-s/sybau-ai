from core import api
from extra import ui, tool_parser, skills
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
        # extract tools and skill requests in the response
        tools, tool_errors = tool_parser.extract_tools_with_errors(response)
        skill_names = tool_parser.extract_skills(response)

        # collect feedback blocks from both tools and skills so a single
        # response can do both in one turn
        feedback_blocks: list[str] = []

        if tools:
            # print all tool names
            names = ", ".join(t.get("name", "?") for t in tools)
            ui.print_tools(names)

            # if multiple found, run all
            results = await executor.run_tools_parallel(tools)

            tool_text = "\n\n".join(f"{tools[i]}\n{str(r)}" for i,r in enumerate(results))

            ui.print_tool_results(tools, results)

            feedback_blocks.append(f"Tool results:\n{tool_text}")

        if skill_names:
            # read each requested skill; support multiple in one turn
            ui.print_tools("read_skill: " + ", ".join(skill_names))

            skill_parts: list[str] = []
            for name in skill_names:
                content = skills.read_skill(name)
                if content is None:
                    skill_parts.append(
                        f"<skill name=\"{name}\">\nError: skill not found.\n</skill>"
                    )
                else:
                    skill_parts.append(
                        f"<skill name=\"{name}\">\n{content}\n</skill>"
                    )

            skill_text = "\n\n".join(skill_parts)
            print(skill_text)

            feedback_blocks.append(f"Skill contents:\n{skill_text}")

        if feedback_blocks:
            # send tool results and/or skill contents back to model
            response, saved_memory = await _stream_agent(
                "\n\n".join(feedback_blocks),
                model_id,
                system_prompt,
                saved_memory
            )

            continue

        return response, saved_memory