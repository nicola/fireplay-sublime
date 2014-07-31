import os
import sys
import sublime
import sublime_plugin
import re
import tempfile
import atexit
import zipfile
import uuid
import json

from twisted.internet import defer
from fireplaylib.fxdevtools.fxconnection import connect, protocol_map
from fireplaylib.fxdevtools.async import MainLoop

from fireplaylib.client import MozClient
from fireplaylib import b2g_helper
from fireplaylib import firefox_helper
reload(sys.modules['fireplay'])
reload(sys.modules['fireplaylib.client'])
reload(sys.modules['fireplaylib.b2g_helper'])
reload(sys.modules['fireplaylib.firefox_helper'])

fp = None
FIREPLAY_CSS = "CSSStyleSheet.prototype.reload = function reload(){\n    // Reload one stylesheet\n    // usage: document.styleSheets[0].reload()\n    // return: URI of stylesheet if it could be reloaded, overwise undefined\n    if (this.href) {\n        var href = this.href;\n        var i = href.indexOf('?'),\n                last_reload = 'last_reload=' + (new Date).getTime();\n        if (i < 0) {\n            href += '?' + last_reload;\n        } else if (href.indexOf('last_reload=', i) < 0) {\n            href += '&' + last_reload;\n        } else {\n            href = href.replace(/last_reload=\\d+/, last_reload);\n        }\n        return this.ownerNode.href = href;\n    }\n};\n\nStyleSheetList.prototype.reload = function reload(){\n    // Reload all stylesheets\n    // usage: document.styleSheets.reload()\n    for (var i=0; i<this.length; i++) {\n        this[i].reload()\n    }\n};"
FIREPLAY_CSS_RELOAD = "document.styleSheets.reload()"
FIREPLAY_RELOAD = "location.reload()"



from twisted.internet import defer
from twisted.internet.defer import setDebugging

from fireplaylib.fxdevtools.protocol import connect
from fireplaylib.fxdevtools import fxconnection
import json

setDebugging(False)

class Fireplay:
    '''
    The Fireplay main client
    '''
    # TODO Blocking at the moment
    def __init__(self, host, port):
        # self.client = MozClient(host, port)
        self.client = None
        self.tabs = None
        self.selected_tab = None
        self.selected_app = None
        self.connected = None
        self.host = host
        self.port = port
        self.loop = MainLoop(protocol_map, self.poke)

    def poke(self):
        print "poking!"
        sublime.set_timeout(self.loop.process, 0)

    def connect(self):
        return defer.maybeDeferred(self._connect)

    def _connect(self):
        if self.connected:
            return self.connected

        # XXX: grab port and hostname from settings maybe?
        self.connected = connect(self.host, self.port)
        self.connected.addCallback(self._connected)

        self.loop.start()

        return self.connected

    def _connected(self, client):
        print "setting connected to %s" % (self.client,)
        self.client = client
        self.connected = client


    def errback(self, e):
        print "ERROR: %s" % (e,)


    # TODO what about force?
    @defer.inlineCallbacks
    def get_tabs(self):
        if (self.tabs):
            defer.returnValue(self.tabs)
            return

        root = yield self.client.root.list_tabs()
        print "UUU", root
        self.tabs = root['tabs']
        defer.returnValue(self.tabs)

    # TODO allow multiple tabs with multiple codebase
    def select_tab(self, tab):
        self.selected_tab = tab

    @defer.inlineCallbacks
    def reload_tab(self):
        # TODO Avoid touching prototype, shrink in one call only
        res = yield self.selected_tab.console.evaluate_js(
            FIREPLAY_RELOAD,
            None
        )
        print res
        defer.returnValue(res)

    @defer.inlineCallbacks
    def reload_css(self):

        # TODO Avoid touching prototype, shrink in one call only
        yield self.selected_tab.console.evaluate_js(
            FIREPLAY_CSS,
            None
        )

        res = yield self.selected_tab.console.evaluate_js(
            FIREPLAY_CSS_RELOAD,
            None
        )
        defer.returnValue(res)

    @defer.inlineCallbacks
    def get_apps(self):
        res = yield self.client.root.webappsActor.getAll()
        defer.returnValue(res['apps'])

    @defer.inlineCallbacks
    def uninstall(self, manifestURL):
        yield self.client.root.webappsActor.close({'manifestURL': manifestURL})
        yield self.client.root.webappsActor.uninstall({'manifestURL': manifestURL})

    @defer.inlineCallbacks
    def launch(self, manifestURL):
        yield self.client.root.webappsActor.launch({'manifestURL': manifestURL})

    def deploy(self, target_app_path, run=True, debug=False):
        app_manifest = get_manifest(target_app_path)[1]

        if run:
            for app in self.get_apps():
                if app['name'] == app_manifest['name']:
                    self.uninstall(app['manifestURL'])

        app_id = self.install(target_app_path)

        for app in self.get_apps():
            if app['id'] == app_id:
                self.selected_app = app
                self.selected_app['local_path'] = target_app_path

        if run:
            self.launch(self.selected_app['manifestURL'])

    def install(self, target_app_path):
        webappsActor = self.root['webappsActor']

        zip_file = zip_path(target_app_path)
        app_file = open(zip_file, 'rb')
        data = app_file.read()
        file_size = len(data)

        upload_res = self.client.send({
            'to': webappsActor,
            'type': 'uploadPackage',
            'bulk': True
        })

        if 'actor' in upload_res and 'BulkActor' in upload_res['actor']:
            packageUploadActor = upload_res['actor']
            self.client.send_bulk(packageUploadActor, data)
        else:
            # Old B2G 1.4 and older
            self.client.send({
                'to': webappsActor,
                'type': 'uploadPackage'
            })
            packageUploadActor = upload_res['actor']
            chunk_size = 4 * 1024 * 1024
            bytes = 0
            while bytes < file_size:
                chunk = data[bytes:bytes + chunk_size]
                self.client.send_chunk(packageUploadActor, chunk)
                bytes += chunk_size

        app_local_id = str(uuid.uuid4())
        reply = self.client.send({
            'to': webappsActor,
            'type': 'install',
            'appId': app_local_id,
            'upload': packageUploadActor
        })
        return reply['appId']

    def inject_css(self):

        webappsActor = self.root['webappsActor']
        res = self.client.send({
            'to': webappsActor,
            'type': 'getAppActor',
            'manifestURL': self.selected_app['manifestURL']
        })

        styleSheetsActor = res['actor']['styleSheetsActor']
        res = self.client.send({
            'to': styleSheetsActor,
            'type': 'getStyleSheets'
        })

        # TODO upload all css always? this should be a setting
        for styleSheet in res['styleSheets']:
            base_path = self.selected_app['local_path']
            manifest_path = self.selected_app['origin']
            css_path = styleSheet['href']
            css_file = base_path + css_path.replace(manifest_path, '')
            f = open(css_file, 'r')

            self.client.send({
                'to': styleSheet['actor'],
                'type': 'update',
                'text': f.read(),
                'transition': True
            })

            # TODO it is blocking. FXDEVTOOLS? new thread?
            self.client.receive()
            self.client.receive()
            self.client.receive()


class FireplayCssReloadOnSave(sublime_plugin.EventListener):
    '''
    Listener on save
    '''
    def on_post_save(self, view):
        global fp

        if not fp:
            return

        reload_on_save = get_setting('reload_on_save')

        # TODO this should be a setting
        if re.search(get_setting('reload_on_save_regex_styles'), view.file_name()):

            # try:
                if fp.client.root.hello["applicationType"] == 'browser':
                    fp.reload_css()
                else:
                    fp.inject_css()
            # except:
            #     fp = None
            #     view.run_command('fireplay_start')

        elif reload_on_save and re.search(get_setting('reload_on_save_regex_reload'), view.file_name()):
            # try:
                if fp.client.root.hello["applicationType"] == 'browser':
                    fp.reload_tab()
                    pass
                else:
                    fp.deploy(fp.selected_app['local_path'])
            # except:
            #     fp = None
            #     view.run_command('fireplay_start')



class FireplayStartAnyCommand(sublime_plugin.TextCommand):
    '''
    The Fireplay command to connect Firefox or FirefoxOS to a given port
    '''
    def run(self, edit, port=6000):
        global fp

        if not fp:
            print "NOT"
            fp = Fireplay('localhost', port)

        print "connecting"
        d = fp.connect()
        d.addCallback(self.start_fireplay)

    def start_fireplay(self, something):
        print something
        print "connection exists"
        if fp.client.root.hello["applicationType"] == 'browser':
            print "browser"
            self.show_tabs()
        else:
            self.show_manifests()

    @defer.inlineCallbacks
    def show_tabs(self):
        print "getting the tabs"
        tabs = yield fp.get_tabs()
        print "got em", tabs
        self.tabs = [t for t in tabs if t.url.find('about:') == -1]
        items = [t.url for t in self.tabs]
        items.append("Disconnect from Firefox")
        self.view.window().show_quick_panel(items, self.selecting_tab)

    def show_manifests(self):
        folders = self.view.window().folders()
        self.manifests = list(filter(None, (get_manifest(f) for f in folders)))

        if not self.manifests:
            print 'Nothing in here'
            return

        items = [self.pretty_name(m) for m in self.manifests]
        items.append("Disconnect from FirefoxOS")
        self.view.window().show_quick_panel(items, self.selecting_manifest)

    def selecting_tab(self, index):
        global fp

        if index == -1:
            return
        if index == len(self.tabs):
            fp = None
            self.view.run_command('fireplay_start')
            return

        fp.select_tab(self.tabs[index])

    def selecting_manifest(self, index):
        global fp
        if index == -1:
            return

        if index == len(self.manifests):
            fp = None
            self.view.run_command('fireplay_start')
            return

        folder = self.manifests[index][0]

        try:
            fp.deploy(folder)
        except:
            fp = None
            self.view.run_command('fireplay_start')

    def pretty_name(self, manifest):
        return '{0} - {1}'.format(manifest[1]['name'], manifest[1]['description'])


class FireplayStartFirefoxCommand(sublime_plugin.TextCommand):
    '''
    The Fireplay command for Firefox Desktop
    '''
    def run(self, edit):
        global fp

        # Start Firefox instance
        # self.view.run_command('fireplay_start_any', {'port': self.ports[index]})
        firefox_helper.start()


class FireplayStartFirefoxOsCommand(sublime_plugin.TextCommand):
    '''
    The Fireplay command for Firefox Os
    '''

    def run(self, edit):
        global fp

        # Start FirefoxOS instance
        simulators_map = b2g_helper.find_b2gs()
        self.simulators = [(k, sim) for k, sims in simulators_map.iteritems() for sim in sims]
        items = [sim[1] for sim in self.simulators]

        if len(items) == 1:
            self.selecting_simulator(0)
        else:
            self.view.window().show_quick_panel(items, self.selecting_simulator)

    def selecting_simulator(self, index):
        # TODO this part looks too hacky
        ext_path, b2g_version = self.simulators[index]
        b2g_helper.run_simulator(ext_path, b2g_version)

        # window.run_command('exec', {
        #     "cmd": [b2g_bin, '-profile "%s"' % b2g_profile, '-start-debugger-server 6666', '-no-remote']
        # })


class FireplayStartCommand(sublime_plugin.TextCommand):
    '''
    The Fireplay main quick panel menu
    '''
    def run(self, editswi):
        global fp

        mapping = {}
        print "fireplay i am starting", fp
        if fp:
            print "STARTING FIREPLAY"
            self.view.run_command('fireplay_start_any')
            return

        rdp_ports = b2g_helper.discover_rdp_ports()

        if rdp_ports['firefox']:
            for port in rdp_ports['firefox']:
                mapping[port] = 'Firefox on %s' % port
        else:
            mapping['firefox'] = 'Start new Firefox instance'

        if rdp_ports['firefoxos']:
            for port in rdp_ports['firefoxos']:
                mapping[port] = 'FirefoxOS on %s' % port
        else:
            mapping['firefoxos'] = 'Start new FirefoxOS instance'

        items = mapping.values()
        self.ports = mapping.keys()
        self.view.window().show_quick_panel(items, self.selecting_port)

    def selecting_port(self, index):
        if index == -1:
            return

        if self.ports[index] == 'firefox':
            self.view.run_command('fireplay_start_firefox')
        elif self.ports[index] == 'firefoxos':
            self.view.run_command('fireplay_start_firefox_os')
        else:
            self.view.run_command('fireplay_start_any', {'port': self.ports[index]})


def get_setting(key):
        s = sublime.load_settings('fireplay.sublime-settings')
        if s and s.has(key):
                return s.get(key)


def zipdir(path, zipfilename):
    try:
        zip_mode = zipfile.ZIP_DEFLATED
    except:
        zip_mode = zipfile.ZIP_STORED

    zipf = zipfile.ZipFile(zipfilename, 'w', zip_mode)
    files_to_compress = []
    for root, dirs, files in os.walk(path):
        for file in files:
            files_to_compress += [(root, file)]

    n = 1
    for tuple in files_to_compress:
        (root, file) = tuple
        filename = os.path.join(root, file)
        # filesize = os.path.getsize(filename)
        path_in_archive = os.path.relpath(filename, path)
        n += 1
        zipf.write(os.path.join(root, file), path_in_archive)
    zipf.close()


def get_manifest(target_app_path):
    if os.path.isdir(target_app_path):
        manifest_file = os.path.join(target_app_path, 'manifest.webapp')
        if not os.path.isfile(manifest_file):
            print "Error: Failed to find FFOS packaged app manifest file '%s'! That directory does not contain a packaged app?" % manifest_file
            return None
        return (target_app_path, json.loads(open(manifest_file, 'r').read()))

    elif target_app_path.endswith('.zip') and os.path.isfile(target_app_path):
        try:
            z = zipfile.ZipFile(target_app_path, 'r')
            bytes = z.read('manifest.webapp')
        except Exception, e:
            print "Error: Failed to read FFOS packaged app manifest file 'manifest.webapp' in zip file '%s'! Error: %s" % target_app_path, str(e)
            return None
        return (target_app_path, json.loads(str(bytes)))

    else:
        print "Error: Path '%s' is neither a directory or a .zip file to represent the location of a FFOS packaged app!" % target_app_path
        return None

    return None


def zip_path(target_app_path):
    (oshandle, tempzip) = tempfile.mkstemp(suffix='.zip', prefix='fireplay_')
    zipdir(target_app_path, tempzip)

    # Remember to delete the temporary package after we quit.
    def delete_temp_file():
        os.remove(tempzip)

    atexit.register(delete_temp_file)
    return tempzip
