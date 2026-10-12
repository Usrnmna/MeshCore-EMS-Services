# Command program organization

- Every shipped MeshCore command must have its own executable Python program in
  each platform package's `scripts/` directory: `meshcore_mqtt_service/scripts/`
  and `meshcore_mqtt_service_windows/scripts/`.
- Register each command with its dedicated program in the corresponding
  `config.json`. Do not register multiple commands against a generic dispatcher
  selected by fixed arguments.
- Reusable parsing, data access, formatting, and geometry code may remain in
  shared helper modules. A dedicated entry point must select its own command
  behavior and support direct Python invocation.
- Keep paired implementations, configuration, tests, and documentation aligned.
  Run `tests/test_command_programs.py` in both packages after adding or changing
  command registrations.
- Preserve existing service ownership of persistent scheduling and subscriptions.
  A standalone lookup must not claim that a subscription was created.
