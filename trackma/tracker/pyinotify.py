# This file is part of Trackma.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import pyinotify

import os
import re

from trackma.tracker import tracker
from trackma import utils

class pyinotifyTracker(tracker.TrackerBase):
    name = 'Tracker (pyinotify)'

    open_pathname = None

    def __init__(self, messenger, tracker_list, process_name, watch_dir, interval, update_wait, update_close, not_found_prompt):
        super().__init__(messenger, tracker_list, process_name, watch_dir, interval, update_wait, update_close, not_found_prompt)

        self.re_players = re.compile(self.process_name.encode('utf-8'))

    def _is_being_played(self, filename):
        """
        This function makes sure that the filename is being played
        by the player specified in players.

        It uses procfs so if we're using inotify that means we're using Linux
        thus we should be safe.
        """

        for p in os.listdir("/proc/"):
            if not p.isdigit(): continue
            d = "/proc/%s/fd/" % p
            try:
                for fd in os.listdir(d):
                    f = os.readlink(d+fd)
                    if f == filename:
                        # Get process name
                        with open('/proc/%s/cmdline' % p, 'rb') as f:
                            cmdline = f.read()
                            pname = cmdline.partition(b'\x00')[0]
                        self.msg.debug(self.name, 'Playing process: {} {} ({})'.format(p, pname, cmdline))

                        # Check if it's our process
                        if self.re_players.search(pname):
                            return True
            except OSError:
                pass

        self.msg.debug(self.name, "Couldn't find playing process.")
        return False

    def _proc_open(self, pathname, filename):
        self.msg.debug(self.name, 'Got OPEN event: {} {}'.format(pathname, filename))

        if self._is_being_played(pathname):
            self.open_pathname = pathname

            (state, show_tuple) = self._get_playing_show(filename)
            self.msg.debug(self.name, "Got status: {} {}".format(state, show_tuple))
            self.update_show_if_needed(state, show_tuple)
        else:
            self.msg.debug(self.name, "Not played by player, ignoring.")

    def _proc_close(self, pathname):
        self.msg.debug(self.name, 'Got CLOSE event: {}'.format(pathname))

        if pathname == self.open_pathname:
            self.open_pathname = None

            (state, show_tuple) = self._get_playing_show(None)
            self.update_show_if_needed(state, show_tuple)

    def observe(self, watch_dir, interval):
        self.msg.info(self.name, 'Using pyinotify.')
        wm = pyinotify.WatchManager()  # Watch Manager
        mask = (pyinotify.IN_OPEN
                | pyinotify.IN_CLOSE_NOWRITE
                | pyinotify.IN_CLOSE_WRITE
                | pyinotify.IN_CREATE
                | pyinotify.IN_MOVED_FROM
                | pyinotify.IN_MOVED_TO
                | pyinotify.IN_DELETE)

        class EventHandler(pyinotify.ProcessEvent):
            def my_init(self, parent=None):
                self.parent = parent

            def process_IN_OPEN(self, event):
                if not event.mask & pyinotify.IN_ISDIR:
                    self.parent._emit_signal('detected', event.path, event.name)
                    self.parent._proc_open(event.pathname, event.name)

            def process_IN_CLOSE_NOWRITE(self, event):
                if not event.mask & pyinotify.IN_ISDIR:
                    self.parent._emit_signal('detected', event.path, event.name)
                    self.parent._proc_close(event.pathname)

            def process_IN_CLOSE_WRITE(self, event):
                if not event.mask & pyinotify.IN_ISDIR:
                    self.parent._emit_signal('detected', event.path, event.name)
                    self.parent._proc_close(event.pathname)

            def process_IN_CREATE(self, event):
                if not event.mask & pyinotify.IN_ISDIR:
                    self.parent._emit_signal('detected', event.path, event.name)

            def process_IN_MOVED_TO(self, event):
                if not event.mask & pyinotify.IN_ISDIR:
                    self.parent._emit_signal('detected', event.path, event.name)

            def process_IN_MOVED_FROM(self, event):
                if not event.mask & pyinotify.IN_ISDIR:
                    self.parent._emit_signal('removed', event.path, event.name)

            def process_IN_DELETE(self, event):
                if not event.mask & pyinotify.IN_ISDIR:
                    self.parent._emit_signal('removed', event.path, event.name)

        handler = EventHandler(parent=self)
        notifier = pyinotify.Notifier(wm, handler)
        self.msg.debug(self.name, 'Watching directory {}'.format(watch_dir))
        wdd = wm.add_watch(watch_dir, mask, rec=True, auto_add=True)

        try:
            #notifier.loop()
            timeout = None
            while self.active:
                if notifier.check_events(timeout):
                    notifier.read_events()
                    notifier.process_events()
                    if self.last_state == utils.TRACKER_NOVIDEO or self.last_updated:
                        timeout = None  # Block indefinitely
                    else:
                        timeout = 1000  # Check each second for counting
                else:
                    self.msg.debug(self.name, "Sending last state {} {}".format(self.last_state, self.last_show_tuple))
                    self.update_show_if_needed(self.last_state, self.last_show_tuple)
        finally:
            notifier.stop()
            self.msg.info(self.name, 'Tracker has stopped.')

