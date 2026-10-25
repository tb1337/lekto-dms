"""Tasks: requests through a webhook that expect an answer (`domain.tasks`).

- `desk`: placing the tasks a node needs, in the unit of work that stores the node's run:
  sent at once if their webhook has room, else waiting.
- `settling`: what follows when a task ends or may be sent: the node that waits for it runs
  anew (`Delegation`), and the next waiting task of its webhook gets its chance.
- `service`: the consumer's answer, and the ends of tasks at their deadline.
"""
