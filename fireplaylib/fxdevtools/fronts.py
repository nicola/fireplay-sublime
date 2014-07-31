"""
Front specializations
"""

from protocol import Front, Request
from marshallers import get_type, add_type, DictType, ActorType

add_type(DictType("tablist", {
  "selected": "number",
  "tabs": "array:tab",
  "webappsActor": "webapps"
}))

add_type(DictType("webapp", {
  "manifestURL": "string"
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
        self.console = get_type("console").read(form["consoleActor"], self)
        for name in form.keys():
            setattr(self, name, form[name])

    def formData(key):
        return self._form[key]

class ConsoleFront(Front):
    actor_desc = {
        "typeName": "console",
        "category": "actor",
        "methods": [{
            "name": "evaluateJS",
            "request": {
                "text": { "_arg": 0, "type": "string" },
                "frameActor": { "_arg": 1, "type": "nullable:json" }
            },
            "response": { "_retval": "nullable:json" }
        }]
    }

    def __init__(self, conn):
        self.conn = conn
        self.actor_id = "console"
        super(ConsoleFront, self).__init__(conn)

class WebappsFront(Front):
    actor_desc = {
        "typeName": "webapps",
        "category": "actor",
        "methods": [{
            "name": "getAll",
            "request": {},
            "response": {
                "apps": { "_retval": "array:webapp" }
            }
        }]
    }

    def __init__(self, conn):
        self.conn = conn
        self.actor_id = "webapps"
        super(WebappsFront, self).__init__(conn)
