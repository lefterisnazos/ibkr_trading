import pydot
import os
import webbrowser

class TreeNode:
    def __init__(self, data):
        self.data = data
        self.children = []

    def add_child(self, child):
        self.children.append(child)

def build_graph(node, graph):
    """
    Recursively add pydot nodes and edges for each TreeNode.
    """
    # Create a unique ID for each node object (using its memory address)
    node_id = str(id(node))
    # Use the node's data as the label
    graph.add_node(pydot.Node(node_id, label=str(node.data)))

    for child in node.children:
        child_id = str(id(child))
        graph.add_node(pydot.Node(child_id, label=str(child.data)))

        # Create an edge from parent (node) to child
        graph.add_edge(pydot.Edge(node_id, child_id))

        # Recursively build sub-branches
        build_graph(child, graph)

# -------------------------
# 1) Create a small tree
# -------------------------
root = TreeNode("Root")
child_a = TreeNode("Child A")
child_b = TreeNode("Child B")

root.add_child(child_a)
root.add_child(child_b)

child_a.add_child(TreeNode("Grandchild A1"))
child_a.add_child(TreeNode("Grandchild A2"))

child_b.add_child(TreeNode("Grandchild B1"))
child_b.add_child(TreeNode("Grandchild B2"))

# -------------------------
# 2) Build the pydot graph
# -------------------------
graph = pydot.Dot("my_tree", graph_type="digraph", rankdir="TB")
# rankdir="TB" makes the graph top-to-bottom; remove or change to "LR" for left-to-right.

build_graph(root, graph)

# -------------------------
# 3) Write the graph to a PNG file (relative path)
# -------------------------
output_path = "tree.png"
graph.write_png(output_path)

print(f"Tree diagram saved as: {output_path}")

# -------------------------
# 4) (Optional) Open the image in your default viewer
# -------------------------
# Uncomment these lines if you want to auto-open the image after creation:
# abs_path = os.path.abspath(output_path)
# webbrowser.open(abs_path)
