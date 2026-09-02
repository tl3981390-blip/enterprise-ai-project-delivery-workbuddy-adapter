# WorkBuddy Controller Conformance

The adapter may report `CONTROLLER_CONNECTED` only when WorkBuddy itself supplies and the adapter exercises:

1. a trusted `session_id`, `conversation_id`, and `message_id` for each user-controlled transition;
2. distinct host events for user pause, resume, cancel and correction;
3. persistent bridge state; and
4. an enforceable completion interception point.

Current known Hook data does not prove items 1 or 2. Therefore all human-controlled transitions remain rejected. No configuration in this repository enables hooks globally or changes WorkBuddy settings.
