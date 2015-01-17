# Copyright (C) 2011-2014 Nippon Telegraph and Telephone Corporation.
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
The central management of Ryu applications.

- Load Ryu applications
- Provide `contexts` to Ryu applications
- Route messages among Ryu applications

"""

import inspect
import itertools
import logging
import sys
import os

from ryu import cfg
from ryu import utils
from ryu.app import wsgi
from ryu.controller.handler import register_instance, get_dependent_services
from ryu.controller.controller import Datapath
from ryu.controller import event
from ryu.controller.event import EventRequestBase, EventReplyBase
from ryu.lib import hub
from ryu.ofproto import ofproto_protocol

LOG = logging.getLogger('ryu.base.app_manager')

# 辞書型
# キー：クラス名、値：アプリケーションのインスタンス
SERVICE_BRICKS = {}

# Datapathのinitメソッドにおいて呼び出される
# ryu.base.app_manager.lookup_service_brick('ofp_event')
def lookup_service_brick(name):
    return SERVICE_BRICKS.get(name)


def _lookup_service_brick_by_ev_cls(ev_cls):
    return _lookup_service_brick_by_mod_name(ev_cls.__module__)


def _lookup_service_brick_by_mod_name(mod_name):
    return lookup_service_brick(mod_name.split('.')[-1])

# SERVICE_BRICKSにアプリケーションのインスタンスを重複のないように登録する
def register_app(app):
    assert isinstance(app, RyuApp)
    assert app.name not in SERVICE_BRICKS
    SERVICE_BRICKS[app.name] = app
    register_instance(app)


def unregister_app(app):
    SERVICE_BRICKS.pop(app.name)


def require_app(app_name, api_style=False):
    """
    Request the application to be automatically loaded.

    If this is used for "api" style modules, which is imported by a client
    application, set api_style=True.

    If this is used for client application module, set api_style=False.
    """
    if api_style:
        frm = inspect.stack()[2]  # skip a frame for "api" module
    else:
        frm = inspect.stack()[1]
    m = inspect.getmodule(frm[0])  # client module
    m._REQUIRED_APP = getattr(m, '_REQUIRED_APP', [])
    m._REQUIRED_APP.append(app_name)
    LOG.debug('require_app: %s is required by %s', app_name, m.__name__)


class RyuApp(object):
    """
    The base class for Ryu applications.

    RyuApp subclasses are instantiated after ryu-manager loaded
    all requested Ryu application modules.
    __init__ should call RyuApp.__init__ with the same arguments.
    It's illegal to send any events in __init__.

    The instance attribute 'name' is the name of the class used for
    message routing among Ryu applications.  (Cf. send_event)
    It's set to __class__.__name__ by RyuApp.__init__.
    It's discouraged for subclasses to override this.
    """
    # キー：コンテキスト名
    # 値：コンテキストを実装しているクラス名(≠モジュール名である)
    # クラスはapp_mgrによってインスタンス化されて、同一のキーを持つアプリケーション間で共有される 
    # 例：'network': network.Network
    # コンテキストクラスはRyuAppのサブクラスとは「限らない」ことに注意
    
    _CONTEXTS = {}
    """
    A dictionary to specify contexts which this Ryu application wants to use.
    Its key is a name of context and its value is an ordinary class
    which implements the context.  The class is instantiated by app_manager
    and the instance is shared among RyuApp subclasses which has _CONTEXTS
    member with the same key.  A RyuApp subclass can obtain a reference to
    the instance via its __init__'s kwargs as the following.

    Example::

        _CONTEXTS = {
            'network': network.Network
        }

        def __init__(self, *args, *kwargs):
            self.network = kwargs['network']
    """

    _EVENTS = []
    """
    A list of event classes which this RyuApp subclass would generate.
    This should be specified if and only if event classes are defined in
    a different python module from the RyuApp subclass is.
    """

    OFP_VERSIONS = None
    """
    A list of supported OpenFlow versions for this RyuApp.
    The default is all versions supported by the framework.

    Examples::

        OFP_VERSIONS = [ofproto_v1_0.OFP_VERSION,
                        ofproto_v1_2.OFP_VERSION]

    If multiple Ryu applications are loaded in the system,
    the intersection of their OFP_VERSIONS is used.
    """

    @classmethod
    def context_iteritems(cls):
        """
        Return iterator over the (key, contxt class) of application context
        """
        return cls._CONTEXTS.iteritems()

    def __init__(self, *_args, **_kwargs):
        super(RyuApp, self).__init__()
        self.name = self.__class__.__name__
        self.event_handlers = {}        # ev_cls -> handlers:list
        self.observers = {}     # ev_cls -> observer-name -> states:set
        self.threads = []
        # イベントという名のキュー
        self.events = hub.Queue(128)
        if hasattr(self.__class__, 'LOGGER_NAME'):
            self.logger = logging.getLogger(self.__class__.LOGGER_NAME)
        else:
            self.logger = logging.getLogger(self.name)
        self.CONF = cfg.CONF

        # prevent accidental creation of instances of this class outside RyuApp
        class _EventThreadStop(event.EventBase):
            pass
        self._event_stop = _EventThreadStop()
        self.is_active = True

    def start(self):
        """
        Hook that is called after startup initialization is done.
        """
        # AppManager経由でよびだされスレッドを生成する。
        # いずれのアプリも内部的にはループする関数をスレッド化していることに注意。
        self.threads.append(hub.spawn(self._event_loop))

    def stop(self):
        self.is_active = False
        self._send_event(self._event_stop, None)
        hub.joinall(self.threads)

    # handler.py中のregister_instanceメソッドで呼び出されている
    def register_handler(self, ev_cls, handler):
        assert callable(handler)
        self.event_handlers.setdefault(ev_cls, [])
        self.event_handlers[ev_cls].append(handler)

    def unregister_handler(self, ev_cls, handler):
        assert callable(handler)
        self.event_handlers[ev_cls].remove(handler)
        if not self.event_handlers[ev_cls]:
            del self.event_handlers[ev_cls]

    def register_observer(self, ev_cls, name, states=None):
        states = states or set()
        ev_cls_observers = self.observers.setdefault(ev_cls, {})
        ev_cls_observers.setdefault(name, set()).update(states)

    def unregister_observer(self, ev_cls, name):
        observers = self.observers.get(ev_cls, {})
        observers.pop(name)

    def unregister_observer_all_event(self, name):
        for observers in self.observers.values():
            observers.pop(name, None)

    def observe_event(self, ev_cls, states=None):
        brick = _lookup_service_brick_by_ev_cls(ev_cls)
        if brick is not None:
            brick.register_observer(ev_cls, self.name, states)

    def unobserve_event(self, ev_cls):
        brick = _lookup_service_brick_by_ev_cls(ev_cls)
        if brick is not None:
            brick.unregister_observer(ev_cls, self.name)

    def get_handlers(self, ev, state=None):
        """Returns a list of handlers for the specific event.

        :param ev: The event to handle.
        :param state: The current state. ("dispatcher")
                      If None is given, returns all handlers for the event.
                      Otherwise, returns only handlers that are interested
                      in the specified state.
                      The default is None.
        """
        ev_cls = ev.__class__
        handlers = self.event_handlers.get(ev_cls, [])
        if state is None:
            return handlers

        def test(h):
            if not hasattr(h, 'callers') or ev_cls not in h.callers:
                # dynamically registered handlers does not have
                # h.callers element for the event.
                return True
            states = h.callers[ev_cls].dispatchers
            if not states:
                # empty states means all states
                return True
            return state in states

        return filter(test, handlers)

    def get_observers(self, ev, state):
        observers = []
        for k, v in self.observers.get(ev.__class__, {}).iteritems():
            if not state or not v or state in v:
                observers.append(k)

        return observers

    def send_request(self, req):
        """
        Make a synchronous request.
        Set req.sync to True, send it to a Ryu application specified by
        req.dst, and block until receiving a reply.
        Returns the received reply.
        The argument should be an instance of EventRequestBase.
        """

        assert isinstance(req, EventRequestBase)
        req.sync = True
        req.reply_q = hub.Queue()
        self.send_event(req.dst, req)
        # going to sleep for the reply
        return req.reply_q.get()
        
    # startメソッド実行時に呼び出される
    def _event_loop(self):
        # アプリごとにスレッド上においてループを回し続ける
        while self.is_active or not self.events.empty():
            # イベントという名のキューから取り出し
            ev, state = self.events.get()
            if ev == self._event_stop:
                continue
            handlers = self.get_handlers(ev, state)
            for handler in handlers:
                # ここでパケットイン等のイベント処理を実行している！？
                handler(ev)

    def _send_event(self, ev, state):
        # ここでキューにイベントをプッシュしている
        self.events.put((ev, state))

    def send_event(self, name, ev, state=None):
        """
        Send the specified event to the RyuApp instance specified by name.
        """

        if name in SERVICE_BRICKS:
            if isinstance(ev, EventRequestBase):
                ev.src = self.name
            LOG.debug("EVENT %s->%s %s" %
                      (self.name, name, ev.__class__.__name__))
            SERVICE_BRICKS[name]._send_event(ev, state)
        else:
            LOG.debug("EVENT LOST %s->%s %s" %
                      (self.name, name, ev.__class__.__name__))
　　
　　# Datapathクラスにおいて呼び出されている
　　# self.ofp_brick.send_event_to_observers(ev, self.state)
    def send_event_to_observers(self, ev, state=None):
        """
        Send the specified event to all observers of this RyuApp.
        """

        for observer in self.get_observers(ev, state):
            self.send_event(observer, ev, state)

    def reply_to_request(self, req, rep):
        """
        Send a reply for a synchronous request sent by send_request.
        The first argument should be an instance of EventRequestBase.
        The second argument should be an instance of EventReplyBase.
        """

        assert isinstance(req, EventRequestBase)
        assert isinstance(rep, EventReplyBase)
        rep.dst = req.src
        if req.sync:
            req.reply_q.put(rep)
        else:
            self.send_event(rep.dst, rep)

    def close(self):
        """
        teardown method.
        The method name, close, is chosen for python context manager
        """
        pass


class AppManager(object):
    # singletone
    _instance = None

    @staticmethod
    def run_apps(app_lists):
        """Run a set of Ryu applications

        A convenient method to load and instantiate apps.
        This blocks until all relevant apps stop.
        """
        app_mgr = AppManager.get_instance()
        app_mgr.load_apps(app_lists)
        contexts = app_mgr.create_contexts()
        services = app_mgr.instantiate_apps(**contexts)
        webapp = wsgi.start_service(app_mgr)
        if webapp:
            services.append(hub.spawn(webapp))
        try:
            hub.joinall(services)
        finally:
            app_mgr.close()

    # デザインパターンでいうところのシングルトン、自身のインスタンスを一つだけ生成する。
    # ryu/ryu/cmd/manager.pyで以下のようにしてapp_mgrの生成に利用されている。
    # app_mgr = AppManager.get_instance()
    @staticmethod
    def get_instance():
        if not AppManager._instance:
            AppManager._instance = AppManager()
        return AppManager._instance

    def __init__(self):
        
        # キー：ユーザが引数で指定するアプリケーションのモジュール名
        # 値：モジュール中のスレッドで必要とするアプリケーションのRyuAppサブクラス
        self.applications_cls = {}
        # キー：アプリケーションの名前、値；アプリケーションのインスタンス
        self.applications = {}
        # 引数に指定されたアプリケーションの_CONTEXTSのキーおよび値
        # コンテキスト名とコンテキストの実装モジュール
        self.contexts_cls = {}
        # 各アプリケーションの_CONTEXTSにおけるキーと実装クラスの「インスタンス」の辞書
        self.contexts = {}

    def load_app(self, name):
        # 組み込み関数の__import__を用いて動的にモジュールをインポート。以降の処理でinspect関数利用の前処理。
        mod = utils.import_module(name)
        
        # inspect.getmembers(object[, predicate]) :「オブジェクトの全メンバーを、 
        # (名前, 値) の組み合わせのリストで返します。リストはメンバー名でソートされています。 
        # predicate が指定されている場合、 predicate の戻り値が真となる値のみを返します。」
        
        # モジュールの中からクラスかつRyuAppのサブクラスかつクラス名とモジュル名と一致するメンバを返す。
        # アプリケーションは「変数・関数・クラス」を含むモジュールの形で指定される。
        # 最終的にはアプリケーション単位でスレッドを生成するが、ここではモジュールからスレッドで必要なRyuAppサブクラスを取得している。
        clses = inspect.getmembers(mod,
                                   lambda cls: (inspect.isclass(cls) and
                                                issubclass(cls, RyuApp) and
                                                mod.__name__ ==
                                                cls.__module__))
        if clses:
            return clses[0][1]
        return None
　　
　　# applications_clsに必要となるアプリケーションのモジュール名、およびRyuAppのサブクラスをすべて登録する
    def load_apps(self, app_lists):
        # 引数が','で区切られた場合のparse。
        # 再度app_listsにリスト化しなおす。
        app_lists = [app for app
                     in itertools.chain.from_iterable(app.split(',')
                                                      for app in app_lists)]
                                                      
        # リストが空になるまで、app_listsから処理対象のアプリケーションをpopしてループする。 
        # アプリケーションが依存するモジュールがあれば、app_listsに追加されることに注意。
        while len(app_lists) > 0:
            app_cls_name = app_lists.pop(0)

            context_modules = map(lambda x: x.__module__,
                                  self.contexts_cls.values())
            # アプリケーションがコンテキストモジュールに含まれていた場合は、以降の処理を飛ばしてからループを再開する。
            # 最初のアプリケーションのコンテキストモジュールが、次のアプリケーションであった場合などが該当する。
            if app_cls_name in context_modules:
                continue

            LOG.info('loading app %s', app_cls_name)

            cls = self.load_app(app_cls_name)
            if cls is None:
                continue

　　　　　　# applications_clsに登録する。
            self.applications_cls[app_cls_name] = cls

            services = []
            
            # RyuAppサブクラスの_CONTEXTSに登録されているキーと値を取得。
            for key, context_cls in cls.context_iteritems():
                
                # 辞書型self.contexts_clsにキーがあればその値を返す、なければキーと値を挿入し値を返す。
                v = self.contexts_cls.setdefault(key, context_cls)
                # RyuAppサブクラス間において、_CONTEXTSのキーと値のペアがずれていないことを確認。
                assert v == context_cls
                # コンテキストを実装しているクラスのモジュール名をリストに追加
                context_modules.append(context_cls.__module__)

                if issubclass(context_cls, RyuApp):
                    # RyuAppのサブクラスは全てスレッドに引き渡す対象となることに注意。
                    # RyuAppサブクラスに対するサービスを取得する。
                    # ryu/ryu/controller/handler.pyに定義されているget_dependent_services
                    # 例として{'dpset': dpset.DPSet}の場合は、最終的にはryu.controller.ofp_handlerがサービスに追加される。
                    services.extend(get_dependent_services(context_cls))

            # we can't load an app that will be initiataed for
            # contexts.
            
            # 上と同じくRyuAppサブクラスに対するサービスを取得する。(例simple_switch -> ofc_handler)
            for i in get_dependent_services(cls):
                if i not in context_modules:
                    services.append(i)
                    
            # pythonのリスト閉包中の倒置if文
            if services:
                # servicesがある場合リストに追加され、ループが延長する。
                app_lists.extend([s for s in set(services)
                                  if s not in app_lists])

    def create_contexts(self):
        for key, cls in self.contexts_cls.items():
            
            # RyuAppのサブクラスならば、インスタンスの作成およびregister_appでSERVICE_BRICKに登録を実施。
            # sサブクラスでないならば、インスタンスを生成するのみ。
            if issubclass(cls, RyuApp):
                # hack for dpset
                context = self._instantiate(None, cls)
            else:
                context = cls()
            LOG.info('creating context %s', key)
            # 重複がないことの確認
            assert key not in self.contexts
            self.contexts[key] = context
        return self.contexts

    def _update_bricks(self):
        for i in SERVICE_BRICKS.values():
            for _k, m in inspect.getmembers(i, inspect.ismethod):
                if not hasattr(m, 'callers'):
                    continue
                for ev_cls, c in m.callers.iteritems():
                    if not c.ev_source:
                        continue

                    brick = _lookup_service_brick_by_mod_name(c.ev_source)
                    if brick:
                        brick.register_observer(ev_cls, i.name,
                                                c.dispatchers)

                    # allow RyuApp and Event class are in different module
                    for brick in SERVICE_BRICKS.itervalues():
                        if ev_cls in brick._EVENTS:
                            brick.register_observer(ev_cls, i.name,
                                                    c.dispatchers)

    @staticmethod
    def _report_brick(name, app):
        LOG.debug("BRICK %s" % name)
        for ev_cls, list_ in app.observers.items():
            LOG.debug("  PROVIDES %s TO %s" % (ev_cls.__name__, list_))
        for ev_cls in app.event_handlers.keys():
            LOG.debug("  CONSUMES %s" % (ev_cls.__name__,))

    @staticmethod
    def report_bricks():
        for brick, i in SERVICE_BRICKS.items():
            AppManager._report_brick(brick, i)

    def _instantiate(self, app_name, cls, *args, **kwargs):
        # for now, only single instance of a given module
        # Do we need to support multiple instances?
        # Yes, maybe for slicing.
        LOG.info('instantiating app %s of %s', app_name, cls.__name__)

        if hasattr(cls, 'OFP_VERSIONS') and cls.OFP_VERSIONS is not None:
            ofproto_protocol.set_app_supported_versions(cls.OFP_VERSIONS)

        if app_name is not None:
            assert app_name not in self.applications
        # アプリケーションのインスタンス化
        app = cls(*args, **kwargs)
        register_app(app)
        assert app.name not in self.applications
        self.applications[app.name] = app
        return app

    def instantiate(self, cls, *args, **kwargs):
        app = self._instantiate(None, cls, *args, **kwargs)
        self._update_bricks()
        self._report_brick(app.name, app)
        return app

    def instantiate_apps(self, *args, **kwargs):
        for app_name, cls in self.applications_cls.items():
            self._instantiate(app_name, cls, *args, **kwargs)

        self._update_bricks()
        self.report_bricks()

        threads = []
        for app in self.applications.values():
            # RyuAppのメソッドstart()中でself.threads.append(hub.spawn(self._event_loop))を呼び出してスレッドを作成している。
            t = app.start()
            if t is not None:
                threads.append(t)
        return threads

    @staticmethod
    def _close(app):
        close_method = getattr(app, 'close', None)
        if callable(close_method):
            close_method()

    def uninstantiate(self, name):
        app = self.applications.pop(name)
        unregister_app(app)
        for app_ in SERVICE_BRICKS.values():
            app_.unregister_observer_all_event(name)
        app.stop()
        self._close(app)
        events = app.events
        if not events.empty():
            app.logger.debug('%s events remians %d', app.name, events.qsize())

    def close(self):
        def close_all(close_dict):
            for app in close_dict.values():
                self._close(app)
            close_dict.clear()

        close_all(self.applications)
        close_all(self.contexts)
