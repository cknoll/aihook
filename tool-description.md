# Tool Description: Interacting with aihook-enabled Python Scripts via curl

## Overview
The `aihook` library allows pausing a running Python script to enable an AI agent (or human user) to interactively execute Python commands in the script's local namespace. This is done by calling `aihook.core.agent_hook(locals())` in the target script, which starts an HTTP server that accepts commands via `curl` or other HTTP clients.

The test script `tests/the-test-script.py` demonstrates this workflow: it defines a `complex_var` dictionary, pauses for agent interaction, then resumes and prints the modified `complex_var`.

## Technical Background
When `agent_hook(locals_dict)` is called:
1. An `AgenticREPL` instance is created, which initializes a Python interactive console bound to the script's local namespace.
2. A lightweight HTTP server is started on `localhost:5000`, with a single endpoint: `POST /execute`.
3. The script pauses execution and waits for HTTP requests containing Python commands to execute.
4. For each valid `POST /execute` request:
   - The request body contains a URL-encoded Python command string.
   - The command is executed in the script's local namespace, with stdout/stderr captured.
   - The captured output is returned as the HTTP response body (plain text, 200 OK).
5. Sending the command `exit()` via `POST /execute` shuts down the server, and the original script resumes execution.

## Step-by-Step Interaction Guide
Follow these steps to interact with a running `aihook`-enabled script like `tests/the-test-script.py` using `curl`:

### Step 1: Start the target Python script
Run the test script (or any script using `agent_hook`) in a terminal:
```bash
python tests/the-test-script.py
```
The script will pause and print:
```
Before hook: complex_var = {'name': 'test_data', 'nested': {'value': 42, 'items': [1, 2, 3, 4]}, 'metadata': {'created': '2026-05-04', 'version': 1.0}}
AgenticREPL: HTTP server running on http://localhost:5000/execute
AgenticREPL: Waiting for agent commands...
```

### Step 2: Send commands via curl
Open a second terminal and use `curl` to send POST requests to the `/execute` endpoint. The command is passed in the request body using the `-d` flag.

#### Example 1: Read a variable value
To print the value of `complex_var["nested"]["value"]`:
```bash
curl -X POST -d 'print(complex_var["nested"]["value"])' http://localhost:5000/execute
```
Response:
```
42
```

#### Example 2: Modify a variable
To update the `items` list in `complex_var`:
```bash
curl -X POST -d 'complex_var["nested"]["items"] = [10, 20, 30]' http://localhost:5000/execute
```
Response: (empty, unless there is output from the command)

#### Example 3: Inspect the full variable
```bash
curl -X POST -d 'print(complex_var)' http://localhost:5000/execute
```
Response:
```
{'name': 'test_data', 'nested': {'value': 42, 'items': [10, 20, 30]}, 'metadata': {'created': '2026-05-04', 'version': 1.0}}
```

### Step 3: Terminate the agent session
When finished, send the `exit()` command to shut down the server and let the script resume:
```bash
curl -X POST -d 'exit()' http://localhost:5000/execute
```
Response:
```
REPL: Exiting
```

Back in the first terminal, the script will resume and print:
```
After hook: complex_var = {'name': 'test_data', 'nested': {'value': 42, 'items': [10, 20, 30]}, 'metadata': {'created': '2026-05-04', 'version': 1.0}}
Main: Script finished.
```

## Notes for AI Agents
1. **Command Format**: Commands must be valid Python statements. Use `print()` to return output, as raw expressions (e.g., `complex_var["nested"]["value"]`) will not produce output unless printed.
2. **URL Encoding**: If commands contain special characters (e.g., spaces, quotes), ensure they are properly URL-encoded for the `curl` request body. `curl` handles basic encoding automatically, but complex commands may require explicit encoding.
3. **Error Handling**: If a command raises an exception, the error message will be captured in stderr and returned in the HTTP response body.
4. **Single Session**: Only one agent session is supported per `agent_hook` call. The server shuts down immediately after receiving the `exit()` command.
5. **Endpoint Restrictions**: Only `POST /execute` is supported. All other endpoints return a 404 error.
