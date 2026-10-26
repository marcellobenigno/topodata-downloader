# -*- coding: utf-8 -*-
def classFactory(iface):
    from .plugin import TopodataDownloaderPlugin
    return TopodataDownloaderPlugin(iface)
