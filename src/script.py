import sys
import json

import xbmc, xbmcaddon

from sys import version_info

from vdlib.util import filesystem
from vdlib.kodi.compat import translatePath

if version_info >= (3, 0):
    from urllib.parse import urlparse, parse_qs
else:
    from urlparse import urlparse, parse_qs    # type: ignore

from torrserve_stream import Settings
ts_settings = Settings()

addon = xbmcaddon.Addon('script.service.torrspy')
addon_id = addon.getAddonInfo('id')

def addon_title():
    return addon.getAddonInfo('name')

def addon_setting(id):
    return addon.getSetting(id)

def addon_base_path():
    base_path = addon_setting('base_path')
    return translatePath(base_path)

def make_path_to_base_relative(path):
    return filesystem.join(addon_base_path(), path)

def log(s):
    message = '[{}: script.py]: {}'.format(addon_id, s)
    xbmc.log(message)

def playing_torrserver_source():
    import xbmc
    player = xbmc.Player()

    if player.isPlayingVideo():
        name = player.getPlayingFile()
        if name:
            if ':{}/'.format(ts_settings.port) in name:
                return True
    return False

def alert(s):
    import xbmcgui
    xbmcgui.Dialog().ok('TorrSpy', s)

def get_params(url):
    res = urlparse(url)
    return parse_qs(res.query)

class Runner(object):
    prefix = 'plugin://script.module.torrspy/'
    tag = '##TorrSpy##'

    def __init__(self, url):
        alert(url)

        command = url.replace(Runner.prefix, '')
        self.__getattribute__(command)()
        
    def run(self):
        if playing_torrserver_source():
            import xbmc, xbmcgui, xbmcplugin

            title = 'My cool new title'
            xbmc_player = xbmc.Player()

            vidIT = xbmc_player.getVideoInfoTag()

            if vidIT.getTagLine() == self.tag:
                return

            item = xbmcgui.ListItem()
            url = xbmc_player.getPlayingFile()
            item.setPath(url)
            item.setInfo('video', {'tagline' : self.tag})
            xbmc_player.updateInfoTag(item)


def Test():
    Runner('plugin://script.module.torrspy/run')
    pass

def save_video_info(hash, video_info):
    if 'imdbnumber' not in video_info:
        return

    log('---TorrSpy: save_info---')

    with filesystem.fopen(get_video_info_path(hash, create_path=True), 'w') as vi_out: 
        json.dump(video_info, vi_out)

def get_video_info_path(hash, create_path=False):
    path = make_path_to_base_relative('.data')
    if create_path and not filesystem.exists(path):
        filesystem.makedirs(path)
    filename = '{}.video_info.json'.format(hash)
    return filesystem.join(path, filename)

def load_video_info(hash):
    video_info_path = get_video_info_path(hash)
    if filesystem.exists(video_info_path):
        with filesystem.fopen(video_info_path, 'r') as vi_in:
            return json.load(vi_in)

def save_strm(file_path, play_url):
    # action="play_now", magnet=magneturi, selFile=0
    from vdlib.util import urlencode

    params = {
            'action' : 'play_now',
            'play_url': play_url
        }
    queryString = urlencode(params, encoding='utf-8')

    link = 'plugin://{}/?{}'.format(
        'plugin.video.torrserve-next',
        queryString
    )

    with filesystem.fopen(file_path, 'w') as out:
        out.write(link)

def save_movie(video_info, play_url):

    import xbmcgui
    save_to_lib = xbmcgui.Dialog().yesno(addon_title(), u'Кино не досмотрено. Сохранить для последующего просмотра?')
    if not save_to_lib:
        return

    original_title = video_info.get('original_title')
    year = video_info.get('year')
    if original_title and year:
        name = u'{}({})'.format(original_title, year)
        save_strm(make_path_to_base_relative('Movies/' + name + '.strm'), play_url)
        #    nfo = name + '.nfo'


def get_info():
    log('---TorrSpy: get_info---')
    import xbmc, xbmcgui
    xbmc.sleep(2*1000)
    item = xbmcgui.ListItem()
    url = xbmc.Player().getPlayingFile()
    item.setPath(url)

    from torrserve_stream import Engine

    hash = Engine.extract_hash_from_play_url(url)
    engine = Engine(hash=hash, host=ts_settings.host, port=ts_settings.port)

    video_info = engine.get_video_info()
    if video_info:
        log('Get info from TorrServer')

    if not video_info:
        video_info = load_video_info(hash)

    if not video_info:
        log('Extract info')
        from .detect import extract_title_date, extract_filename     # type: ignore
        filename = extract_filename(url)
        title, year = extract_title_date(filename)
        video_info = {'title': title, 'year': year}

    item.setInfo('video', video_info)

    art = engine.get_art()
    if art:
        item.setArt(art)

    xbmc.Player().updateInfoTag(item)
    log('---TorrSpy---')
    log(xbmc.Player().getPlayingFile())

    save_video_info(hash, video_info)

def open_settings():
    import xbmcaddon
    addon = xbmcaddon.Addon()
    addon.openSettings()

def create_playlists():    
    from vdlib.kodi.compat import translatePath
    src_dir = translatePath('special://home/addons/script.service.torrspy/resources/playlists')
    dst_dir = translatePath('special://profile/playlists/video')

    from xbmcvfs import copy, listdir
    from os.path import join
    _, files = listdir(src_dir)
    for file in files:
        copy(join(src_dir, file), join(dst_dir, file))

    from xbmc import executebuiltin
    executebuiltin('ActivateWindow(Videos, {}, return)'.format('special://profile/playlists/video'))

def create_sources():
    from xbmcgui import Dialog
    # Dialog().ok(addon_title(), 'Not implemented')

    from xbmcaddon import Addon

    base_path = addon_base_path()
    restart_msg = u'Чтобы изменения вступили в силу, нужно перезапустить KODI. Перезапустить?'

    from vdlib.kodi.sources import create_movies_and_tvshows
    if create_movies_and_tvshows(base_path):
        if Dialog().yesno(addon_title(), restart_msg):
            xbmc.executebuiltin('Quit')

def main():
    #Runner(sys.argv[0])
    log('---TorrSpy---')
    for i in sys.argv:
        log(i)
    log('---TorrSpy---')

    def arg_exists(arg, index):
        try:
            return sys.argv.index(arg) == index
        except ValueError:
            return False

    if arg_exists('get_info', 1):
        get_info()
    elif arg_exists('create_playlists', 1):
        create_playlists()
    elif arg_exists('create_sources', 1):
        create_sources()
    else:
        open_settings()