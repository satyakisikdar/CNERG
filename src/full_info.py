"""
Full info extraction and generation

Uses explicit boundary information containing node level info on boundary nodes and edges
"""

import networkx as nx
import random
import numpy as np
from copy import deepcopy

import vrgs.globals as globals
from vrgs.Rule import FullRule as Rule
from vrgs.globals import find_boundary_edges


def deduplicate_edges(edges):
    """
    Takes an iterable of edges and makes sure there are no reverse edges
    :param edges: iterable of edges
    :return: uniq_edges: unique set of edges
    """
    uniq_edges = set()
    for u, v in edges:
        if (v, u) not in uniq_edges:
            uniq_edges.add((u, v))
    return uniq_edges


def extract_vrg(g, tree, lvl):
    """
    Extract a vertex replacement grammar (specifically an ed-NRC grammar) from a graph given a dendrogram tree

    :param g: graph to extract from
    :param tree: dendrogram with nodes at the bottom.
    :return: List of Rule objects
    """
    rule_list = list()
    if not isinstance(tree, list):
        # if we are at a leaf, then we need to backup one level
        return rule_list

    for index, subtree in enumerate(tree):
        # build the grammar from a left-to-right bottom-up tree ordering (in order traversal)
        rule_list.extend(extract_vrg(g, subtree, lvl+1))
        if not isinstance(subtree, list):
            # if we are at a leaf, then we need to backup one level
            continue

        # subtree to be replaced
        # print(subtree, lvl)

        sg = g.subgraph(subtree)

        nbunch = set()  # nbunch stores the set of original nodes in the graph
        for node in sg:
            if '_' in str(node):
                nbunch.update(globals.clusters[node])
            else:
                nbunch.add(node)
        # print('st:', subtree, nbunch)

        edges_covered = set(globals.original_graph.edges_iter(nbunch))  # this includes all the internal edges
        # print(sg.edges())
        boundary_edges = find_boundary_edges(g, subtree)
        # print('lhs: ', len(boundary_edges))

        for u, v in boundary_edges:   # just iterates over the incoming edges since it's undirected
            if '_' in str(u) and '_' in str(v):   # u & v are globals.clusters
                cut_edges = set(nx.edge_boundary(globals.original_graph, globals.clusters[u], globals.clusters[v]))
                edges_covered.update(cut_edges)
                # print(u, v, globals.clusters[u], globals.clusters[v], cut_edges)
            elif '_' in str(u):  # u is a cluster
                cut_edges = set(nx.edge_boundary(globals.original_graph, globals.clusters[u], [v]))
                edges_covered.update(cut_edges)
                # print(u, v, globals.clusters[u], cut_edges)
            elif '_' in str(v):  # v is a cluster
                cut_edges = set(nx.edge_boundary(globals.original_graph, globals.clusters[v], [u]))
                edges_covered.update(cut_edges)
                # print(u, v, globals.clusters[v], cut_edges)
            else:  # both are nodes
                cut_edges = {(u, v)}
                edges_covered.update(cut_edges)
                # print(u, v, cut_edges)
        # print('edges covered', subtree, edges_covered)

        for u, v in boundary_edges:
            sg.add_edge(u, v, attr_dict={'b': True})

        rule = Rule()
        rule.lhs = len(boundary_edges)
        rule.graph = sg
        rule.internal_nodes = subtree
        rule.level = lvl
        rule.edges_covered = deduplicate_edges(edges_covered)
        rule.generalize_rhs()
        rule.contract_rhs()

        # next we contract the original graph
        [g.remove_node(n) for n in subtree]

        new_node = min(subtree)

        # replace subtree with new_node
        tree[index] = new_node
        g.add_node(new_node, attr_dict={'label': rule.lhs})

        # rewire new_node
        subtree = set(subtree)

        for u, v in boundary_edges:
            if u in subtree:
                u = new_node
            if v in subtree:
                v = new_node
            g.add_edge(u, v)


        new_node = '_{}'.format(new_node)  # add an extra '_' for clusters
        globals.clusters[new_node] = set()
        for node in subtree:
            if '_' in str(node):  # node is a cluster
                globals.clusters[new_node].update(globals.clusters[node])
            else:
                globals.clusters[new_node].add(node)

        rule_list.append(rule)
    return rule_list


def generate_graph(rule_dict):
    """
    Create a new graph from the VRG at random
    :param rule_dict: List of unique VRG rules
    :return: newly generated graph
    """
    node_counter = 1
    non_terminals = set()
    new_g = nx.MultiGraph()

    new_g.add_node(0, attr_dict={'label': 0})
    non_terminals.add(0)

    while len(non_terminals) > 0:      # continue until no more non-terminal nodes exist
        # choose a non terminal node at random
        node_sample = random.sample(non_terminals, 1)[0]
        lhs = new_g.node[node_sample]['label']

        rhs_candidates = rule_dict[lhs]
        if len(rhs_candidates) == 1:
            rhs = rhs_candidates[0]
        else:
            weights = np.array([rule.frequency for rule in rhs_candidates])
            weights = weights / np.sum(weights)   # normalize into probabilities
            idx = int(np.random.choice(range(len(rhs_candidates)), size=1, p=weights))  # pick based on probability
            rhs = rhs_candidates[idx]

        max_v = -1
        for v in rhs.graph.nodes_iter():
            if isinstance(v, int):
                max_v = max(v, max_v)
        max_v += 1

        # expanding the 'Iso' nodes into separate integer labeled nodes
        if rhs.graph.has_node('Iso'):
            for u, v in rhs.graph.edges():
                if u == 'I':
                    rhs.graph.remove_edge(u, v)
                    rhs.graph.add_edge(max_v, v, attr_dict={'b': True})
                    max_v += 1

                elif v == 'Iso':
                    rhs.graph.remove_edge(u, v)
                    rhs.graph.add_edge(u, max_v, attr_dict={'b': True})
                    max_v += 1

            assert rhs.graph.degree('Iso') == 0
            rhs.graph.remove_node('Iso')

        broken_edges = find_boundary_edges(new_g, [node_sample])

        assert len(broken_edges) == lhs, 'expected {}, got {}'.format(lhs, len(broken_edges))

        new_g.remove_node(node_sample)
        non_terminals.remove(node_sample)

        nodes = {}

        for n, d in rhs.graph.nodes_iter(data=True):
            if isinstance(n, str):
                new_node = node_counter
                nodes[n] = new_node
                new_g.add_node(new_node, attr_dict=d)
                if 'label' in d:  # if it's a new non-terminal add it to the set of non-terminals
                    non_terminals.add(new_node)
                node_counter += 1

        for u, v, d in rhs.graph.edges_iter(data=True):
            if 'b' not in d:  # (u, v) is not a boundary edge
                  new_g.add_edge(nodes[u], nodes[v])

        # randomly assign broken edges to boundary edges
        random.shuffle(broken_edges)

        boundary_edge_count = 0
        for u, v,  d in rhs.graph.edges_iter(data=True):
            if 'b' in d:  # (u, v) is a boundary edge
                boundary_edge_count += 1

        assert len(broken_edges) >= boundary_edge_count, 'broken edges {}, boundary edges {}'.format(len(broken_edges),
                                                                                                    boundary_edge_count)
        for u, v,  d in rhs.graph.edges_iter(data=True):
            if 'b' not in d:  # (u, v) is not a boundary edge
                continue

            b_u, b_v = broken_edges.pop()
            if isinstance(u, str):  # u is internal
                if b_u == node_sample:  # b_u is the sampled node
                    new_g.add_edge(nodes[u], b_v)
                else:
                    new_g.add_edge(nodes[u], b_u)
            else:  # v is internal
                if b_u == node_sample:
                    new_g.add_edge(nodes[v], b_v)
                else:
                    new_g.add_edge(nodes[v], b_u)

    return new_g