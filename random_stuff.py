from typing import List


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
        while cur and index<0:
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
        while cur  and index <0:
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




















