# SPDX-FileCopyrightText: Copyright (c) 2025 Tod Kurt
# SPDX-License-Identifier: MIT

import time

from arpeggiator import Arpeggiator


def note_on(note):
    print("note on  %d %.2f" % (note, time.monotonic()))
    
def note_off(note):
    print("     off %d %.2f" % (note, time.monotonic()))

arp = Arpeggiator(120, note_on, note_off)

arp.start()
print("hi")

arp.add_note(48)
arp.add_note(50)
arp.add_note(52)

while True:
    for _ in range(50):
        arp.update()
        time.sleep(0.05)
        
    print("boop")    
    arp.del_note(50)
    
    for _ in range(50):
        arp.update()
        time.sleep(0.01)
    
