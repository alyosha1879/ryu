# Copyright (C) 2012 Nippon Telegraph and Telephone Corporation.
# Copyright (C) 2011 Isaku Yamahata <yamahata at valinux co jp>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
OpenFlow event definitions.
"""
# 実際にはofp_eventに関するクラスは動的に追加されることに注意。

import inspect

from ryu.controller import handler
from ryu import ofproto
from ryu import utils
from . import event


class EventOFPMsgBase(event.EventBase):
    def __init__(self, msg):
        super(EventOFPMsgBase, self).__init__()
        self.msg = msg


#
# Create ofp_event type corresponding to OFP Msg
#

_OFP_MSG_EVENTS = {}


def _ofp_msg_name_to_ev_name(msg_name):
    return 'Event' + msg_name


def ofp_msg_to_ev(msg):
    return ofp_msg_to_ev_cls(msg.__class__)(msg)


def ofp_msg_to_ev_cls(msg_cls):
    name = _ofp_msg_name_to_ev_name(msg_cls.__name__)
    return _OFP_MSG_EVENTS[name]


def _create_ofp_msg_ev_class(msg_cls):
    # nameに引数のクラスの名称を代入
    name = _ofp_msg_name_to_ev_name(msg_cls.__name__)
    # print 'creating ofp_event %s' % name

　　# 重複を防ぐ
    if name in _OFP_MSG_EVENTS:
        return
    # 組み込み関数 type()を使ってクラスのオブジェクトを生成することができる。
    # type(str クラス名, tuple 基底クラス, dict プロパティ)
    cls = type(name, (EventOFPMsgBase,),
               dict(__init__=lambda self, msg:
                    super(self.__class__, self).__init__(msg)))
    # 現在のグローバルシンボルテーブルを表す辞書。グローバル変数として上で生成したクラスを登録する。
    # eg. name='EventOFPPacketIn', cls=<class 'ryu.controller.ofp_event.EventOFPPacketIn'>)
    globals()[name] = cls
    _OFP_MSG_EVENTS[name] = cls


def _create_ofp_msg_ev_from_module(ofp_parser):
    # print mod
    for _k, cls in inspect.getmembers(ofp_parser, inspect.isclass):
    　　# @_set_msg_type(msg_type)でデコレータされている場合
    　　# eg. @_set_msg_type(ofproto.OFPT_PACKET_IN)
        #     class OFPPacketIn(MsgBase):
        if not hasattr(cls, 'cls_msg_type'):
            continue
        _create_ofp_msg_ev_class(cls)

# ryu/ryu/cmd/manager.py => ryu/ryu/controller/controller.py => from ryu.controller import ofp_event 経由でimportされる。
# モジュールのimport時に実行され、ここのforループ中でofp_eventに関するクラスを動的に生成している。
for ofp_mods in ofproto.get_ofp_modules().values():
    ofp_parser = ofp_mods[1]
    # ofproto_v1_0_parser,ofproto_v1_1_parser,ofproto_v1_2_parser,ofproto_v1_3_parserでループする。
    # print 'loading module %s' % ofp_parser
    _create_ofp_msg_ev_from_module(ofp_parser)


class EventOFPStateChange(event.EventBase):
    def __init__(self, dp):
        super(EventOFPStateChange, self).__init__()
        self.datapath = dp


handler.register_service('ryu.controller.ofp_handler')
