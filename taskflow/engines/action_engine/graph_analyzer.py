# -*- coding: utf-8 -*-

#    Copyright (C) 2013 Yahoo! Inc. All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from networkx.algorithms import traversal
import six

from taskflow import retry as r
from taskflow import states as st


class GraphAnalyzer(object):
    """Analyzes a execution graph to get the next nodes for execution or
    reversion by utilizing the graphs nodes and edge relations and comparing
    the node state against the states stored in storage.
    """

    def __init__(self, graph, storage):
        self._graph = graph
        self._storage = storage

    @property
    def execution_graph(self):
        return self._graph

    def get_next_nodes(self, node=None):
        if node is None:
            execute = self.browse_nodes_for_execute()
            revert = self.browse_nodes_for_revert()
            return execute + revert

        state = self.get_state(node)
        intention = self._storage.get_atom_intention(node.name)
        if state == st.SUCCESS:
            if intention == st.REVERT:
                return [node]
            elif intention == st.EXECUTE:
                return self.browse_nodes_for_execute(node)
            else:
                return []
        elif state == st.REVERTED:
            return self.browse_nodes_for_revert(node)
        elif state == st.FAILURE:
            return self.browse_nodes_for_revert()
        else:
            return []

    def browse_nodes_for_execute(self, node=None):
        """Browse next nodes to execute for given node if specified and
        for whole graph otherwise.
        """
        if node:
            nodes = self._graph.successors(node)
        else:
            nodes = self._graph.nodes_iter()

        available_nodes = []
        for node in nodes:
            if self._is_ready_for_execute(node):
                available_nodes.append(node)
        return available_nodes

    def browse_nodes_for_revert(self, node=None):
        """Browse next nodes to revert for given node if specified and
        for whole graph otherwise.
        """
        if node:
            nodes = self._graph.predecessors(node)
        else:
            nodes = self._graph.nodes_iter()

        available_nodes = []
        for node in nodes:
            if self._is_ready_for_revert(node):
                available_nodes.append(node)
        return available_nodes

    def _is_ready_for_execute(self, task):
        """Checks if task is ready to be executed."""

        state = self.get_state(task)
        intention = self._storage.get_atom_intention(task.name)
        transition = st.check_task_transition(state, st.RUNNING)
        if not transition or intention != st.EXECUTE:
            return False

        task_names = []
        for prev_task in self._graph.predecessors(task):
            task_names.append(prev_task.name)

        task_states = self._storage.get_atoms_states(task_names)
        return all(state == st.SUCCESS and intention == st.EXECUTE
                   for state, intention in six.itervalues(task_states))

    def _is_ready_for_revert(self, task):
        """Checks if task is ready to be reverted."""

        state = self.get_state(task)
        intention = self._storage.get_atom_intention(task.name)
        transition = st.check_task_transition(state, st.REVERTING)
        if not transition or intention not in (st.REVERT, st.RETRY):
            return False

        task_names = []
        for prev_task in self._graph.successors(task):
            task_names.append(prev_task.name)

        task_states = self._storage.get_atoms_states(task_names)
        return all(state in (st.PENDING, st.REVERTED)
                   for state, intention in six.itervalues(task_states))

    def iterate_subgraph(self, retry):
        """Iterates a subgraph connected to current retry controller, including
        nested retry controllers and its nodes.
        """
        for _src, dst in traversal.dfs_edges(self._graph, retry):
            yield dst

    def iterate_retries(self, state=None):
        """Iterates retry controllers of a graph with given state or all
        retries if state is None.
        """
        for node in self._graph.nodes_iter():
            if isinstance(node, r.Retry):
                if not state or self.get_state(node) == state:
                    yield node

    def iterate_all_nodes(self):
        for node in self._graph.nodes_iter():
            yield node

    def find_atom_retry(self, atom):
        return self._graph.node[atom].get('retry')

    def is_success(self):
        for node in self._graph.nodes_iter():
            if self.get_state(node) != st.SUCCESS:
                return False
        return True

    def get_state(self, node):
        return self._storage.get_atom_state(node.name)
