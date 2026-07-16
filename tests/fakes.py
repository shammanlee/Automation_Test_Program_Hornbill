class FakeVisaResource:
    def __init__(self, address, events, failing_commands=(), close_fails=False):
        self.resource_name = address
        self.timeout = None
        self.events = events
        self.failing_commands = set(failing_commands)
        self.close_fails = close_fails
        self.closed = False

    def write(self, command):
        if self.closed:
            raise RuntimeError("resource is closed")
        self.events.append(("write", self.resource_name, command))
        if command in self.failing_commands:
            raise RuntimeError(f"failed command: {command}")

    def query(self, command):
        self.write(command)
        return "OK"

    def close(self):
        self.closed = True
        self.events.append(("resource_close", self.resource_name))
        if self.close_fails:
            raise RuntimeError("resource close failed")


class FakeVisaManager:
    def __init__(self, events=None, connect_fails=(), command_failures=None,
                 close_fails=()):
        self.events = events if events is not None else []
        self.connect_fails = set(connect_fails)
        self.command_failures = command_failures or {}
        self.close_fails = set(close_fails)
        self.open_count = 0

    def open_resource(self, address, **kwargs):
        self.open_count += 1
        self.events.append(("open", address))
        if address in self.connect_fails:
            raise RuntimeError("connection failed")
        return FakeVisaResource(
            address,
            self.events,
            self.command_failures.get(address, ()),
            address in self.close_fails,
        )

    def close(self):
        self.events.append(("manager_close",))
