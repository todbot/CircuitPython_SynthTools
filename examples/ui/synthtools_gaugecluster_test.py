# SPDX-FileCopyrightText: Copyright (c) 2024 Tod Kurt
#
# SPDX-License-Identifier: Unlicense

import time

import board
import displayio

from synthtools.ui import GaugeCluster

display = board.DISPLAY  # get display objet, assumes built-in display
main_group = displayio.Group()
display.root_group = main_group

num_gauges = 6
cluster = GaugeCluster(num_gauges, x=10, y=10, width=10, height=20, xstride=2.5)

main_group.append(cluster.gauges)
main_group.append(cluster.select_lines)  # indicates which param set is editable
