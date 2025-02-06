from typing import List
import os


class ListNode:

    def __init__(self, val=0):
        self.val = val
        self.prev = None
        self.next = None

class MyLinkedList:

    def __init__(self):
        self.left = ListNode(0)
        self.right = ListNode(0)
        self.left.next = self.right
        self.right.prev = self.left

    def get(self, index: int) -> int:
        cur = self.left.next
        while cur and index>0:
            cur = cur.next
            index =-1

        if cur and index==0 and cur != self.right:
            return cur.val
        else:
            return -1

    def addAtHead(self, val: int) -> None:
        new = ListNode(val)
        new.next = self.left.next
        self.left.next.prev = new
        self.left.next = new
        new.prev = self.left

        # new, next, prev = ListNode(val), self.left.next, self.left
        # next.prev = new
        # prev.next = new
        # new.next = next
        # new.prev = prev

    def addAtTail(self, val: int) -> None:

        new, next, prev  =  ListNode(val), self.right, self.right.prev
        next.prev = new
        prev.next = new
        new.next = next
        new.prev = prev

    def addAtIndex(self, index: int, val: int) -> None:
        cur = self.left.next
        while cur  and index >0:
            index -= 1
            cur = cur.next

        # we add before the index, with same logic as in addAtTail
        new, next, prev = ListNode(val), cur, cur.prev
        next.prev = new
        prev.next = new
        new.next = next
        new.prev = prev

    def deleteAtIndex(self, index: int) -> None:
        pass

class TreeNode:
    def __init__(self, data):
        self.data = data
        self.children = []
        self.parent = None

    def add_child(self, child):
        child.parent = self
        self.children.append(child)

    def get_current_level(self):
        level = 0
        p = self.parent
        while p:
            level += 1
            p = p.parent

        return level

class BinaryTreeSearchNode:

    def __init__(self, data):
        self.data = data
        self.right = None
        self.left = None

    def add_child(self, data):
        if data ==  self.data:
            return
        if data < self.data:
            if self.left:
                self.left.add_child(data)
            else:
                self.left = BinaryTreeSearchNode(data)
        else:
            if self.right:
                self.right.add_child(data)
            else:
                self.right = BinaryTreeSearchNode(data)

    def in_order_traversal(self):
        items = []

        if self.left:
            items += self.left.in_order_traversal()

        items.append(self.data)

        if self.right:
            items += self.right.in_order_traversal()

        return items

    def post_order_traversal(self):
        items = []
        if self.left:
            items += self.left.post_order_traversal()
        if self.right:
            items += self.right.post_order_traversal()

        items.append(self.data)

        return items

    def pre_order_traversal(self):
        items = [self.data]
        if self.left:
            items += self.left.pre_order_traversal()
        if self.right:
            items += self.right.pre_order_traversal()

        return items

    def search_value(self, val):
        if val == self.data :
            return True

        if val < self.data:
            if self.left:
                return self.left.search_value(val)
            else:
                return False
        else:
            if self.right:
                return self.right.search_value(val)
            else:
                return False

    def find_min(self):
        if self.left:
            return self.left.find_min()
        else:
            return self.data

    def find_max(self):
        if self.right:
            return self.right.find_max()
        else:
            return self.data

    def calculate_sum(self):
        if self.left:
            left_sum = self.left.calculate_sum()
        else:
            left_sum = 0

        if self.right:
            right_sum = self.right.calculate_sum()
        else:
            right_sum = 0

        return self.data + left_sum + right_sum

    def delete(self, val):
        if self.data == val:
            if self.right and self.left:
                min_val = self.right.find_min()
                self.data = min_val
                self.right = self.right.delete(min_val)
            elif self.left:
                self.data = self.left.data
                self.left = self.left.delete(self.data)
            elif self.right:
                self.data = self.right.data
                self.right = self.right.delete(self.data)
            else:
                return None

        elif self.data < val:
            if self.right:
                return self.right.delete(val)
        else:
            if self.left:
                return self.left.delete(val)

        return self


def build_thefucking_tree(items):
    root =  BinaryTreeSearchNode(items[0])
    for item in items[1:]:
        root.add_child(item)

    return root


numbers_tree = build_thefucking_tree([17,4,1,20,9,23,18,34])
numbers_tree.delete(20)
print( 'after deleterin 20', numbers_tree.in_order_traversal())













