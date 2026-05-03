import code
import sys
import io
from http.server import HTTPServer, BaseHTTPRequestHandler
from .release import __version__

class AgenticREPL:
    def __init__(self, namespace):
        self.namespace = namespace
        self.console = code.InteractiveConsole(namespace)
        self.stdout_buffer = io.StringIO()
        self.stderr_buffer = io.StringIO()
        self.server = None
        self.running = False

    def execute_command(self, command):
        # Redirect stdout and stderr
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = self.stdout_buffer
        sys.stderr = self.stderr_buffer

        try:
            # Push command to InteractiveConsole
            self.console.push(command)
        except Exception as e:
            print(f"Exception during command execution: {e}", file=sys.stderr)
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
        self.running = True

        # Define request handler with access to REPL instance
        repl_instance = self

        class REPLRequestHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                # Only handle /execute endpoint
                if self.path != '/execute':
                    self.send_response(404)
                    self.send_header('Content-Type', 'text/plain')
                    self.end_headers()
                    self.wfile.write(b"404 Not Found: Only /execute endpoint is supported")
                    return

                # Read request body
                content_length = int(self.headers.get('Content-Length', 0))
                if content_length == 0:
                    self.send_response(400)
                    self.send_header('Content-Type', 'text/plain')
                    self.end_headers()
                    self.wfile.write(b"400 Bad Request: No command provided")
                    return

                body = self.rfile.read(content_length).decode('utf-8')
                command = body.strip()

                # Handle exit command
                if command == "exit()":
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/plain')
                    self.end_headers()
                    self.wfile.write(b"REPL: Exiting\n")
                    repl_instance.running = False
                    # Shutdown server in a separate thread to avoid blocking
                    import threading
                    threading.Thread(target=repl_instance.server.shutdown).start()
                    return

                # Execute command and send response
                output = repl_instance.execute_command(command)
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(output.encode('utf-8'))

            def log_message(self, format, *args):
                # Suppress default request logging to keep output clean
                pass

        # Start HTTP server
        self.server = HTTPServer(('localhost', 5000), REPLRequestHandler)
        print("AgenticREPL: HTTP server running on http://localhost:5000/execute")
        print("AgenticREPL: Waiting for agent commands...")
        self.server.serve_forever()
        self.server.server_close()
        print("AgenticREPL: Server stopped.")

def agent_hook(locals_dict):
    repl = AgenticREPL(locals_dict)
    repl.run()
