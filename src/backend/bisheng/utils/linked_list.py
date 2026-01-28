# -*- coding: utf-8 -*-
from __future__ import print_function


class DoubleNode(object):
    """node_amb"""

    def __init__(self, data):
        # Identity Data Domain
        self.data = data
        # Identify the previous linked domain
        self.prev = None
        # Identify the next linked domain
        self.next = None


class DoubleLinkList(object):
    """Double linked watch"""

    def head(self):
        return self.__head

    def __init__(self, node=None):
        # Private Attribute Header Node
        self.__head = node

    # is_empty() Is the linked list empty
    def is_empty(self):
        return self.__head is None

    # length() Link List Length
    def length(self):
        count = 0  # Number
        # Current Node
        current = self.__head
        while current is not None:
            count += 1
            # Move the current node backward
            current = current.next
        return count

    # travel() Traverse the entire linked list
    def travel(self):
        # Current node accessed
        current = self.__head
        print('[ ', end='')
        while current is not None:
            print(current.data, end=' ')
            current = current.next
        print(']')

    # add(item) Adding elements to the head of a linked list
    def add(self, item):
        node = DoubleNode(item)
        # The next node of the new node is the head node of the old linked list
        node.next = self.__head
        # The header node of the new linked list is the new node
        self.__head = node
        # The previous node of the next node points to the newly added node
        node.next.prev = node

    # append(item) Add an element at the end of the linked list
    def append(self, item):
        node = DoubleNode(item)
        if self.is_empty():
            # When empty node
            self.__head = node
        else:
            # Let the pointer point to the last node
            current = self.__head
            while current.next is not None:
                current = current.next
            # The next of the last node is the newly addednode
            current.next = node
            # Newly added node The previous node is the current node
            node.prev = current

    # search(item) Find out if the node exists
    def search(self, item):
        # Current Node
        current = self.__head
        while current is not None:
            if current.data == item:
                # Found it.
                return True
            else:
                current = current.next
        return False

    def find(self, item):
        # Current Node
        current = self.__head
        while current is not None:
            if current.data == item:
                # Found it.
                return current
            else:
                current = current.next
        return None

    # insert(index, item) Specify location (from0Start) Add Element
    def insert(self, index, item):
        if index <= 0:
            # Insert Before
            self.add(item)
        elif index > (self.length() - 1):
            # Add at the end
            self.append(item)
        else:
            # Create a new section
            node = DoubleNode(item)
            current = self.__head
            # Number of traversals
            count = 0
            # Find the previous node of the inserted node
            while count < index:
                count += 1
                current = current.next
            # The next node of the new node points to the current node
            node.next = current
            # The previous node of the new node points to the previous node of the current node
            node.prev = current.prev
            # The next node of the previous node of the current node points to the new node
            current.prev.next = node
            # The previous node of the current node points to the new node
            current.prev = node

    # remove(item) Delete node
    def remove(self, item):
        current = self.__head
        while current is not None:
            if current.data == item:
                # Locate the node element you want to delete
                if current == self.__head:
                    # Head Node
                    self.__head = current.next
                    if current.next:
                        # If there is not only one node left,
                        current.next.prev = None
                else:
                    # The next node of the previous node of the current node points to the next node of the current node
                    current.prev.next = current.next
                    if current.next:
                        # If the last element is not deleted, the previous node of the next node of the current node points to the previous node of the current node
                        current.next.prev = current.prev
                return  # Return to current node
            else:
                # Nothing found, move backward
                current = current.next


if __name__ == '__main__':
    print('test:')
    double_link_list = DoubleLinkList()


    for i in range(10):
        double_link_list.append(str(i)+":hello")



    print('--------Determine if it is empty-------')
    print(double_link_list.is_empty())
    node = double_link_list.find('0:hello')
    t = {}
    t["abc"]="abc"
    t["abc1"]="abc1"

    print("{}",node.next.data)

    print('-----------Longitudinal------------')
    print(double_link_list.length())

    double_link_list.append(2)
    double_link_list.append(3)
    double_link_list.append(5)

    print('-----------Step Through------------')
    double_link_list.travel()

    double_link_list.add(1)
    print('-----------Step Through------------')
    double_link_list.travel()
    double_link_list.add(0)
    print('-----------Step Through------------')
    double_link_list.travel()
    double_link_list.insert(4, 4)
    print('-----------Step Through------------')
    double_link_list.travel()
    double_link_list.insert(-1, -1)

    print('-----------Step Through------------')
    double_link_list.travel()

    print('-----------Cari------------')
    print(double_link_list.search(4))

    print('-----------Delete------------')
    double_link_list.remove(5)
    double_link_list.remove(-1)

    print('-----------Step Through------------')
    double_link_list.travel()

    print('-----------Longitudinal------------')
    print(double_link_list.length())
