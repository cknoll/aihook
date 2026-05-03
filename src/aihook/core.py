import code
import sys
import io
import socket
from .release import __version__

class AgenticREPL:
    def __init__(self, namespace):
        self.namespace = namespace
        self.console = code.InteractiveConsole(namespace)
        self.stdout_buffer = io.StringIO()
        self.stderr_buffer = io.StringIO()
        self.server_socket = None
        self.client_socket = None

    def start_server(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(('localhost', 5000))
        self.server_socket.listen(1)
        print("AgenticREPL: Waiting for agent connection on port 5000...")
        self.client_socket, addr = self.server_socket.accept()
        print(f"AgenticREPL: Agent connected from {addr}")

    def execute_command(self, command):
        # Redirect stdout and stderr
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = self.stdout_buffer
        sys.stderr = self.stderr_buffer

        try:
            # Push command to InteractiveConsole
            self.console.push(command)
        finally:
            # Restore stdout and stderr
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        # Get captured output
        stdout_output = self.stdout_buffer.getvalue()
        stderr_output = self.stderr_buffer.getvalue()

        # Clear buffers for next command
        self.stdout_buffer.seek(0)
        self.stdout_buffer.truncate(0)
        self.stderr_buffer.seek(0)
        self.stderr_buffer.truncate(0)

        return stdout_output + stderr_output

    def run(self):
        self.start_server()
        try:
            while True:
                # Receive command from agent
                data = self.client_socket.recv(4096)
                if not data:
                    break
                command = data.decode('utf-8').strip()
                if command == "exit()":
                    self.client_socket.sendall(b"REPL: Exiting\n")
                    break
                else:
                    output = self.execute_command(command)
                    # Send output back to agent
                    self.client_socket.sendall(output.encode('utf-8'))
        finally:
            if self.client_socket:
                self.client_socket.close()
            if self.server_socket:
                self.server_socket.close()

def agent_hook(locals_dict):
    repl = AgenticREPL(locals_dict)
    repl.run()
