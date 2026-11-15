"""A conversation on one interval of one well: any number of questions, each answered by the question graph on the
same prepared well and the same ledger, with one append-only log the conversation is resumed and audited from.

    from petroharness.session import Conversation
    c = Conversation.start("WELL.las", "my-session", formation="...", tops="tops.csv")
    c.ask("What is the porosity distribution?").answer
    c.ask("What if I use the density porosity instead?").answer
    Conversation.resume("my-session").ask("Now relate water saturation to porosity.")

The first question is answered exactly as petroharness.ask answers it. docs/SESSIONS.md.
"""
from petroharness.session.conversation import Conversation, Turn  # noqa: F401
