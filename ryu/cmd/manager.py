#!/usr/bin/env python
#
# Copyright (C) 2011, 2012 Nippon Telegraph and Telephone Corporation.
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

from ryu.lib import hub
hub.patch()

# TODO:
#   Right now, we have our own patched copy of ovs python bindings
#   Once our modification is upstreamed and widely deployed,
#   use it
#
# NOTE: this modifies sys.path and thus affects the following imports.
# eg. oslo.config.cfg.
import ryu.contrib

from ryu import cfg
import logging
import sys

from ryu import log
log.early_init_log(logging.DEBUG)

from ryu import flags
from ryu import version
from ryu.app import wsgi
from ryu.base.app_manager import AppManager
from ryu.controller import controller
# controllerのimportの際にofp_eventもimportされる。
# その際にofp_eventに動的にクラスが生成されることに注意。
from ryu.topology import switches


CONF = cfg.CONF
CONF.register_cli_opts([
    cfg.ListOpt('app-lists', default=[],
                help='application module name to run'),
    cfg.MultiStrOpt('app', positional=True, default=[],
                    help='application module name to run'),
    cfg.StrOpt('pid-file', default=None, help='pid file name'),
])


def main(args=None, prog=None):
    try:
        CONF(args=args, prog=prog,
             project='ryu', version='ryu-manager %s' % version,
             default_config_files=['/usr/local/etc/ryu/ryu.conf'])
    except cfg.ConfigFilesNotFoundError:
        CONF(args=args, prog=prog,
             project='ryu', version='ryu-manager %s' % version)

    log.init_log()

    if CONF.pid_file:
        import os
        with open(CONF.pid_file, 'w') as pid_file:
            pid_file.write(str(os.getpid()))

    # ryu-managerの引数はapp_listsに含まれる。
    app_lists = CONF.app_lists + CONF.app
    
    # keep old behaivor, run ofp if no application is specified.
    # 引数が指定されていな場合は、ofp_handlerが引数に追加される。
    if not app_lists:
        app_lists = ['ryu.controller.ofp_handler']
        
　　# app_mgrの作成（シングルトン）
    app_mgr = AppManager.get_instance()
    # applications_clsに{キー:アプリケーションのモジュール名、値:RyuAppのサブクラス}をすべて登録する。
    # app_listsに含まれないが動作に必要となる、RyuAppで定義されたコンテキストも含まれていることに注意。
    app_mgr.load_apps(app_lists)
    # アプリケーションのコンテキストを実装しているクラスのインスタンス化。
    # RyuAppのサブクラスならSERVICE_BRICKに登録する。
    contexts = app_mgr.create_contexts()
    # services: 各アプリケーションがListenするイベントを実装しているクラスのインスタンスのリスト。
    # e.g ryu/controller/ofp_event.py => ryu.controller.ofp_handler
    services = []
    # アプリケーションのインスタンスを生成。
    # コンテキストは生成時の引数として使用する。
    services.extend(app_mgr.instantiate_apps(**contexts))

    webapp = wsgi.start_service(app_mgr)
    if webapp:
        thr = hub.spawn(webapp)
        services.append(thr)

    try:
        全てのスレッドに対してwaitを呼び出す
        hub.joinall(services)
    finally:
        app_mgr.close()


if __name__ == "__main__":
    main()
