"""
Front specializations
"""

from protocol import Front, Request
from marshallers import get_type, add_type, DictType, ActorType

add_type(DictType("tablist", {
  "selected": "number",
  "tabs": "array:tab",
  "webappsActor": "string"
}))


class RootFront(Front):
    actor_desc = {
        "typeName": "root",
        "methods": [{
            "name": "echo",
            "request": {
                "string": { "_arg": 0, "type": "string" }
            },
            "response": {
                "string": { "_retval": "string" }
            }
          },
        {
            "name": "listTabs",
            "request": {},
            "response": { "_retval": "tablist" }
        },
        {
            "name": "protocolDescription",
            "request": {},
            "response": { "_retval": "json" }
        }],
        "events": {
            "tabListChanged": {}
        }
    }

    def __init__(self, conn, packet):
        self.actor_id = "root"
        self.hello = packet
        self.webapps = get_type("webappsActor").read(packet["webappsActor"], self)
        super(RootFront, self).__init__(conn)


class TabFront(Front):
    actor_desc = {
        "typeName": "tab",
        "methods": [],
    }

    def __init__(self, conn):
        self.conn = conn

    def form(self, form, detail=None):
        self.actor_id = form["actor"]
        self.inspector = get_type("inspector").read(form["inspectorActor"], self)
        self.console = get_type("consoleActor").read(form["consoleActor"], self)
        for name in form.keys():
            setattr(self, name, form[name])

    def formData(key):
        return self._form[key]

class ConsoleActorFront(Front):
    actor_desc = {
        "typeName": "consoleActor",
        "category": "actor",
        "methods": [{
            "name": "evaluateJS",
            "request": {
                "text": { "_arg": 0, "type": "string" },
                "frameActor": { "_arg": 1, "type": "nullable:json" }
            },
            "response": {
                "string": { "_retval": "json" }
            }
        }]
    }

    def __init__(self, conn):
        self.conn = conn
        self.actor_id = "consoleActor"
        super(ConsoleActorFront, self).__init__(conn)

class WebappsActorFront(Front):
    actor_desc = {
        "typeName": "webappsActor",
        "category": "actor",
        "methods": [{
            "name": "evaluateJS",
            "request": {
                "text": { "_arg": 0, "type": "string" },
                "frameActor": { "_arg": 1, "type": "nullable:json" }
            },
            "response": {
                "string": { "_retval": "json" }
            }
        }]
    }

    def __init__(self, conn):
        self.conn = conn
        self.actor_id = "consoleActor"
        super(WebappsActorFront, self).__init__(conn)
