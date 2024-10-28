# -*- coding: utf-8 -*-
from __future__ import print_function


class DoubleNode(object):
    """节点"""

    def __init__(self, data):
        # 标识数据域
        self.data = data
        # 标识前一个链接域
        self.prev = None
        # 标识后一个链接域
        self.next = None


class DoubleLinkList(object):
    """双链表"""

    def head(self):
        return self.__head

    def __init__(self, node=None):
        # 私有属性头结点
        self.__head = node

    # is_empty() 链表是否为空
    def is_empty(self):
        return self.__head is None

    # length() 链表长度
    def length(self):
        count = 0  # 数目
        # 当前节点
        current = self.__head
        while current is not None:
            count += 1
            # 当前节点往后移
            current = current.next
        return count

    # travel() 遍历整个链表
    def travel(self):
        # 访问的当前节点
        current = self.__head
        print('[ ', end='')
        while current is not None:
            print(current.data, end=' ')
            current = current.next
        print(']')

    # add(item) 链表头部添加元素
    def add(self, item):
        node = DoubleNode(item)
        # 新节点的下一个节点为旧链表的头结点
        node.next = self.__head
        # 新链表的头结点为新节点
        self.__head = node
        # 下一个节点的上一个节点指向新增的节点
        node.next.prev = node

    # append(item) 链表尾部添加元素
    def append(self, item):
        node = DoubleNode(item)
        if self.is_empty():
            # 为空节点时
            self.__head = node
        else:
            # 让指针指向最后节点
            current = self.__head
            while current.next is not None:
                current = current.next
            # 最后节点的下一个为新添加的node
            current.next = node
            # 新添加的结点上一个节点为当前节点
            node.prev = current

    # search(item) 查找节点是否存在
    def search(self, item):
        # 当前节点
        current = self.__head
        while current is not None:
            if current.data == item:
                # 找到了
                return True
            else:
                current = current.next
        return False

    def find(self, item):
        # 当前节点
        current = self.__head
        while current is not None:
            if current.data == item:
                # 找到了
                return current
            else:
                current = current.next
        return None

    # insert(index, item) 指定位置（从0开始）添加元素
    def insert(self, index, item):
        if index <= 0:
            # 在前方插入
            self.add(item)
        elif index > (self.length() - 1):
            # 在最后添加
            self.append(item)
        else:
            # 创建新节点
            node = DoubleNode(item)
            current = self.__head
            # 遍历次数
            count = 0
            # 查找到插入节点的上一个节点
            while count < index:
                count += 1
                current = current.next
            # 新节点的下一个节点指向当前节点
            node.next = current
            # 新节点的上一个节点指向当前节点的上一个节点
            node.prev = current.prev
            # 当前节点的上一个节点的下一个节点指向新节点
            current.prev.next = node
            # 当前节点的上一个节点指向新节点
            current.prev = node

    # remove(item) 删除节点
    def remove(self, item):
        current = self.__head
        while current is not None:
            if current.data == item:
                # 找到要删除的节点元素
                if current == self.__head:
                    # 头结点
                    self.__head = current.next
                    if current.next:
                        # 如果不是只剩下一个节点
                        current.next.prev = None
                else:
                    # 当前节点的上一个节点的下一个节点指向当前节点的下一个节点
                    current.prev.next = current.next
                    if current.next:
                        # 如果不是删除最后一个元素，当前节点的下一个节点的上一个节点指向当前节点的上一个节点
                        current.next.prev = current.prev
                return  # 返回当前节点
            else:
                # 没找到，往后移
                current = current.next


if __name__ == '__main__':
    print('test:')
    double_link_list = DoubleLinkList()


    for i in range(10):
        double_link_list.append(str(i)+":hello")



    print('--------判断是否为空-------')
    print(double_link_list.is_empty())
    node = double_link_list.find('0:hello')
    t = {}
    t["abc"]="abc"
    t["abc1"]="abc1"

    print("{}",node.next.data)

    print('-----------长度------------')
    print(double_link_list.length())

    double_link_list.append(2)
    double_link_list.append(3)
    double_link_list.append(5)

    print('-----------遍历------------')
    double_link_list.travel()

    double_link_list.add(1)
    print('-----------遍历------------')
    double_link_list.travel()
    double_link_list.add(0)
    print('-----------遍历------------')
    double_link_list.travel()
    double_link_list.insert(4, 4)
    print('-----------遍历------------')
    double_link_list.travel()
    double_link_list.insert(-1, -1)

    print('-----------遍历------------')
    double_link_list.travel()

    print('-----------查找------------')
    print(double_link_list.search(4))

    print('-----------删除------------')
    double_link_list.remove(5)
    double_link_list.remove(-1)

    print('-----------遍历------------')
    double_link_list.travel()

    print('-----------长度------------')
    print(double_link_list.length())
