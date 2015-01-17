# Copyright (C) 2011-2014 Nippon Telegraph and Telephone Corporation.
# Copyright (C) 2011, 2012 Isaku Yamahata <yamahata at valinux co jp>
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

import inspect
import logging
import sys

LOG = logging.getLogger('ryu.controller.handler')

# just represent OF datapath state. datapath specific so should be moved.
# イベント生成のタイミングを指定するためのdispacher
# 以下の各openflowのネゴシエーションフェイズにおいてイベントが生成される

# 例:
# @set_ev_handler(ofp_event.EventOFPHello, HANDSHAKE_DISPATCHER)
# def hello_handler(self, ev):

# @set_ev_handler(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
# def switch_features_handler(self, ev):

# @set_ev_handler(ofp_event.EventOFPEchoRequest,[HANDSHAKE_DISPATCHER, CONFIG_DISPATCHER, MAIN_DISPATCHER])
# def echo_request_handler(self, ev):

HANDSHAKE_DISPATCHER = "handshake"
CONFIG_DISPATCHER = "config"
MAIN_DISPATCHER = "main"
DEAD_DISPATCHER = "dead"


class _Caller(object):
    """Describe how to handle an event class.
    """

    def __init__(self, dispatchers, ev_source):
        """Initialize _Caller.

        :param dispatchers: A list of states or a state, in which this
                            is in effect.
                            None and [] mean all states.
        :param ev_source: The module which generates the event.
                          ev_cls.__module__ for set_ev_cls.
                          None for set_ev_handler.
        """
        self.dispatchers = dispatchers
        self.ev_source = ev_source


# should be named something like 'observe_event'

# Ryuアプリケーションに特定のイベント(ev_cls)をlistenさせるデコレータ 
# イベント発生時にデコレータ対象のhandlerが呼び出される

# 引数付きのデコレータ関数
# 使用例
#     @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
#     def _packet_in_handler(self, ev):
def set_ev_cls(ev_cls, dispatchers=None):
    def _set_ev_cls_dec(handler):
        if 'callers' not in dir(handler):
            handler.callers = {}
        for e in _listify(ev_cls):
            handler.callers[e] = _Caller(_listify(dispatchers), e.__module__)
        return handler
    return _set_ev_cls_dec

# メソッドをイベント制御用のハンドラー化させるデコレータ

# 使用例
# SampleRequest発生時にsample_request_handlerが呼び出される
# デコレート対象のメソッドに辞書型アトリビュートを追加する（既にあれば何もしない）
#
# class SampleRequest(EventRequestBase):
#
# @set_ev_cls(SampleRequest)
# def sample_request_handler(self, request):

def set_ev_handler(ev_cls, dispatchers=None):
    def _set_ev_cls_dec(handler):
        if 'callers' not in dir(handler):
            # デコレート対象の「メソッド」に対して、辞書型のアトリビュートcallersを追加。
            # ここで初めてcallersが追加されるため、最初からcallersをアトリビュートとして持っていないことに注意。
            handler.callers = {}
        # 引数としてのev_clsをリスト化してforループで回している
        for e in _listify(ev_cls):
            # callersはキーにev_cls、値にdispatchersをセットする。
            handler.callers[e] = _Caller(_listify(dispatchers), None)
        return handler
    return _set_ev_cls_dec


def _has_caller(meth):
    return hasattr(meth, 'callers')

# 引数がリストでない場合はリストに入れて返す
def _listify(may_list):
    if may_list is None:
        may_list = []
    if not isinstance(may_list, list):
        may_list = [may_list]
    return may_list


def register_instance(i):
    for _k, m in inspect.getmembers(i, inspect.ismethod):
        # LOG.debug('instance %s k %s m %s', i, _k, m)
        if _has_caller(m):
            for ev_cls, c in m.callers.iteritems():
                i.register_handler(ev_cls, m)

# app_mgrにて、RyuAppのサブクラスであるclsおよびcontext_clsを引数として呼び出される。
# cls:アプリケーションモジュール中のRyuAppのサブクラス。
# context_cls:cls中の_CONTEXTSで定義された、コンテキストの実装クラス。
# 両クラスの@set_ev_handlerがlistenしているイベントを実装しているモジュールを取り出し、そのモジュールの_SERVICE_NAMEを取り出す。
# eg. @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER) => ofp_event => ryu.controller.ofp_handler
def get_dependent_services(cls):
    services = []
    # コンテキスト実装クラスからメソッドを（名前、値）で取り出し。
    for _k, m in inspect.getmembers(cls, inspect.ismethod):
        # もしメソッドにcallersという属性がある場合 = @set_ev_handlerでデコレートされている場合
        if _has_caller(m):
            # callerのイベント名およびディスパッチャーの両方を取り出し
            for ev_cls, c in m.callers.iteritems():
                # ロード済みモジュールの[モジュール名とモジュールオブジェクトの]辞書sys.modulesの中からイベントクラスev_clsのモジュール名を取得。
                # そのモジュール名に対して、下のregister_serviceメソッドで定義された_SERVICE_NAMEを取り出す
                service = getattr(sys.modules[ev_cls.__module__],
                                  '_SERVICE_NAME', None)
                if service:
                    # avoid cls that registers the own events (like
                    # ofp_handler)
                    if cls.__module__ != service:
                        services.append(service)

    # sys.module は、Python が開始されてからインポートされた全てのモジュールを辞書である。
    # ： キーはモジュール名、値はモジュール・オブジェクトである。
    # コンテキスト実装クラスのモジュールオブジェクトを取得。
    m = sys.modules[cls.__module__]
    # mから_REQUIRED_APPの属性の値を返す（なければ[]）
    services.extend(getattr(m, '_REQUIRED_APP', []))
    # set: 順序の保証がないオブジェクト、それをリスト化している
    services = list(set(services))
    return services


def register_service(service):
    """
    Register the ryu application specified by 'service' as
    a provider of events defined in the calling module.

    If an application being loaded consumes events (in the sense of
    set_ev_cls) provided by the 'service' application, the latter
    application will be automatically loaded.

    This mechanism is used to e.g. automatically start ofp_handler if
    there are applications consuming OFP events.
    """
    # 呼び出し元スタックのフレームレコードのリストを返します。
    # 最初の要素は呼び出し元のフレームレコードで、末尾の要素はスタックにある最も外側のフレームのフレームレコードとなります。
    frm = inspect.stack()[1]
    m = inspect.getmodule(frm[0])
    # 呼び出し元モジュールに_SERVICE_NAMEを登録している。
    m._SERVICE_NAME = service
