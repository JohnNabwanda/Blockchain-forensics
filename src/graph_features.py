"""Graph-derived features computed with NetworkX (feature Set 3).

Only structural features are used. No labels are read here, so there is no label leakage
from the test period. In Elliptic, payment flows stay within a single time step, so each
time step's graph is processed independently.
"""
import networkx as nx
import pandas as pd

GRAPH_COLS = [
    "g_in_degree", "g_out_degree", "g_total_degree", "g_pagerank",
    "g_two_hop_size", "g_component_size", "g_clustering", "g_nbr_mean_degree",
]


def build_graph(nodes, edges):
    G = nx.DiGraph()
    G.add_nodes_from(nodes["txId"])
    G.add_edges_from(edges[["src", "dst"]].itertuples(index=False, name=None))
    return G


def compute_graph_features(nodes, edges):
    G = build_graph(nodes, edges)
    step_of = dict(zip(nodes["txId"], nodes["time_step"]))
    out = []
    for step, ids in nodes.groupby("time_step")["txId"]:
        H = G.subgraph(ids)
        U = H.to_undirected()
        pr = nx.pagerank(H, alpha=0.85) if H.number_of_edges() else {n: 1 / len(H) for n in H}
        comp = {}
        for c in nx.connected_components(U):
            for n in c:
                comp[n] = len(c)
        clust = nx.clustering(U)
        for n in H.nodes:
            nbrs = set(U.neighbors(n))
            two_hop = set(nbrs)
            for m in nbrs:
                two_hop.update(U.neighbors(m))
            two_hop.discard(n)
            deg = U.degree(n)
            out.append({
                "txId": n,
                "g_in_degree": H.in_degree(n),
                "g_out_degree": H.out_degree(n),
                "g_total_degree": deg,
                "g_pagerank": pr[n] * len(H),       # normalised so 1.0 = average node in its time step
                "g_two_hop_size": len(two_hop),
                "g_component_size": comp[n],
                "g_clustering": clust[n],
                "g_nbr_mean_degree": (sum(U.degree(m) for m in nbrs) / deg) if deg else 0.0,
            })
    cross = sum(1 for a, b in G.edges if step_of[a] != step_of[b])
    if cross:
        print(f"  note: {cross} edges cross time steps and were ignored for graph features")
    return nodes.merge(pd.DataFrame(out), on="txId", how="left")


def neighbourhood(G, tx_id, hops=1, max_nodes=60):
    """Sub-graph around one transaction, for the dashboard."""
    U = G.to_undirected(as_view=True)
    keep = {tx_id}
    frontier = {tx_id}
    for _ in range(hops):
        nxt = set()
        for n in frontier:
            nxt.update(U.neighbors(n))
        keep |= nxt
        frontier = nxt
        if len(keep) >= max_nodes:
            break
    keep = list(keep)[:max_nodes] if len(keep) > max_nodes else list(keep)
    if tx_id not in keep:
        keep[0] = tx_id
    return G.subgraph(keep).copy()
