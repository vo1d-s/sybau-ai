import asyncio
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from extra.models import MODELS
from extra import storage, ui
from config.settings import DEFAULT_MODEL
from config import system_prompt
from core import agent

# All commands that can be ran
COMMANDS = [
    "/models",
    "/model",
    "/skills"
]

class CommandCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.current_line_before_cursor

        for cmd in COMMANDS:
            if cmd.startswith(text):
                yield Completion(
                    cmd,
                    start_position=-len(text)
                )

# Chat loop
async def main_loop():
    kb = KeyBindings()

    # Enter -> send
    @kb.add("enter")
    def _enter(event: KeyPressEvent):

        for kp in event.key_sequence:

            if getattr(kp, "data", None) and "\n" in kp.data:
                event.current_buffer.insert_text("\n")
                return

        event.current_buffer.validate_and_handle()

    # Alt+Enter -> newline
    @kb.add("escape", "enter")
    def _alt_enter(event: KeyPressEvent):
        event.current_buffer.insert_text("\n")
    
    # Create the prompt session (input + autocompletion)
    session = PromptSession(
        key_bindings=kb,
        multiline=True,
        enable_open_in_editor=True,
        completer=CommandCompleter(),
        refresh_interval=0.25,
    )

    # Load necessary files
    config_data = storage.load_config() # All saved config as dict
    saved_memory = []

    # set default model
    config_data["model_id"] = DEFAULT_MODEL
    storage.save_config(config_data)

    # print selected model (startup)
    ui.print_models_load(config_data.get("model_id"))

    # Actual chat loop
    while True:
        # Wait for an input
        res: str = await session.prompt_async(" > ")
        text = res.strip() # Remove spaces on start and end
        print()

        # For command execution
        cmd = None # string of command name if there's one
        arg = None # string of word after if there's one

        if text.startswith("/"):
            splitted = text.split(" ", 1)

            cmd = splitted[0][1:] # first word, command without prefix
            arg = splitted[1] if len(splitted) > 1 else None # arg if exists

        # check command name
        if cmd == "models":
            for model in MODELS:
                print(f'{model["id"]} ({model["name"]})')

        elif cmd == "model":
            # set model_id and save after
            config_data["model_id"] = arg
            storage.save_config(config_data)

        elif cmd == "skills":
            from extra import skills as skills_mod

            choice = ui.arrow_select(
                "Skills",
                [
                    ("Check existing skills", "List skills in the current folder"),
                    ("Select new skills folder", "Pick a different skills directory"),
                ],
            )

            if choice == 0:
                ui.print_skills(skills_mod.list_skills())
            elif choice == 1:
                folder = ui.pick_folder()
                if folder:
                    new_dir = skills_mod.set_skills_dir(folder)
                    ui.console.print(
                        f"[bright_green]Skills folder set to:[/bright_green] {new_dir}"
                    )
                    ui.print_skills(skills_mod.list_skills())
                else:
                    ui.console.print("[bright_black]Cancelled.[/bright_black]")

        # if no cmd, continue chatting
        if not cmd:
            # add user content to the conversation
            saved_memory.append({
                "role": "user",
                "content": text
            })

            # generate response
            response, saved_memory = await agent.run_agent(
                user_message=text, 
                model_id=config_data["model_id"],
                system_prompt=system_prompt.AGENT_PROMPT,
                memory=saved_memory
            )

def run():
    # print title
    ui.print_title()
    asyncio.run(main_loop())