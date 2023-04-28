# -*- coding: utf-8 -*-

import sys, json, re
#from vdlib.scrappers.movieapi import imdb_cast
from sys import version_info
from time import sleep, time
from typing import Pattern

MINUTES = 60
HOURS = 3600
DAYS = HOURS * 24

import requests

from vdlib.util import filesystem, urlparse, parse_qs
from vdlib.torrspy.info import addon_set_setting, addon_setting, addon_title, make_path_to_base_relative, load_video_info, save_video_info, save_art, addon_base_path
from vdlib.torrspy.player_video_info import PlayerVideoInfo

from vdlib.torrspy.detect import is_video, extract_filename, extract_title_date, extract_original_title_year, find_tmdb_movie_item
from vdlib.torrspy.strm_utils import save_movie, save_tvshow, save_movie_strm, save_tvshow_strms

from torrserve_stream.engine import Engine
from vdlib.torrspy.strm_utils import ts_settings

def log(s):
    from vdlib.torrspy import _unit_log
    _unit_log('script.py', s)

def is_torrserve_v2_link(url):
    pattern = r'http://.+/stream/.+\?link=[a-f\d]{40}&index=\d+&play'
    return re.match(pattern, url) is not None

def is_torrserve_v1_link(url):
    pattern = r'http://.+/torrent/view/[a-f\d]{40}/'
    return re.match(pattern, url) is not None

def playing_torrserver_source():
    # type: () -> bool
    import xbmc
    player = xbmc.Player()

    if player.isPlayingVideo():
        name = player.getPlayingFile()
        if name:
            if ':{}/'.format(ts_settings.port) in name or is_torrserve_v2_link(name) or is_torrserve_v1_link(name):
                return True
            
    return False

def alert(s):
    import xbmcgui
    xbmcgui.Dialog().ok('TorrSpy', s)

def get_params(url):
    res = urlparse(url)
    return parse_qs(res.query)

def get_recent_episodes(fields):
    import datetime
    today = datetime.date.today()
    today.strftime('%Y-%m-%d')

    from vdlib.kodi.jsonrpc_requests import VideoLibrary

    filter = {
        "operator": "startswith",
        "field": "dateadded",
        "value": today.strftime('%Y-%m-%d')
    }
    limits = {
        "start": 0,
        "end": 100
    }
    sort = {
        "method": "dateadded",
        "order": "descending"
    }
    properties = [
        "title",
        "thumbnail",
        "playcount",
        "lastplayed",
        "dateadded",
        "episode",
        "season",
        "rating",
        "file",
        "cast",
        "showtitle",
        "tvshowid",
        "uniqueid",
        "resume",
        "firstaired",
        "fanart"
    ]
    result = VideoLibrary.GetEpisodes(filter=filter, limits=limits, sort=sort, properties=fields)

def get_info():
    log('---TorrSpy: get_info---')
    import xbmc, xbmcgui
    xbmc.sleep(2*1000)
    item = xbmcgui.ListItem()
    url = xbmc.Player().getPlayingFile()
    item.setPath(url)

    hash = Engine.extract_hash_from_play_url(url)
    engine = Engine(hash=hash, host=ts_settings.host, port=ts_settings.port, auth=ts_settings.auth)

    video_info = get_video_info_from_engine(engine)            

    art = engine.get_art()

    saved_video_info = load_video_info(hash)
    if saved_video_info:
        video_info = saved_video_info

    if not video_info:
        video_info = detect_video_info_from_title(engine.title)

    if not video_info:
        video_info = detect_video_info_from_filename(extract_filename(url))

    def update_listitem(video_info, art):
        if video_info: item.setInfo('video', video_info)
        if art: item.setArt(art)

        xbmc.Player().updateInfoTag(item)

    log('---TorrSpy---')
    log(xbmc.Player().getPlayingFile())

    update_listitem(video_info, art)

    if 'imdbnumber' not in video_info:
        update_video_info_from_tmdb(video_info)
        update_listitem(video_info, art)

    save_video_info(hash, video_info)
    save_art(hash, art)

    return video_info, art

def detect_video_info_from_filename(filename):
    log('Extract info')
    title, year = extract_title_date(filename)
    video_info = {}
    if year:
        video_info['year'] = year
    if title:
        video_info['title'] = title
    return video_info

def get_video_info_from_engine(engine, data=None):
    log('Get info from TorrServer')
    video_info = engine._get_video_info_from_data(data) if data else engine.get_video_info()
    #if video_info:
    #    update_video_info(video_info)
    return video_info

def detect_video_info_from_title(title):
    r = extract_original_title_year(title)
    return r

# def update_video_info(video_info):
#     if 'imdbnumber' not in video_info:
#         if 'title' in video_info and not 'originaltitle' in video_info:
#             video_info.update(extract_original_title_year(video_info['title']))

def update_video_info_from_tmdb(video_info):
    tmdb_movie_item = find_tmdb_movie_item(video_info)
    if tmdb_movie_item:
        imdbnumber = tmdb_movie_item.imdb()
        video_info.update(tmdb_movie_item.get_info())
        if imdbnumber:
            video_info['imdbnumber'] = imdbnumber
        if tmdb_movie_item.type == 'movie':
            video_info['mediatype'] = 'movie'
        elif tmdb_movie_item.type == 'tv':
            video_info['mediatype'] = 'tvshow'

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
    from xbmcaddon import Addon
    from xbmc import executebuiltin

    base_path = addon_base_path()
    restart_msg = u'Чтобы изменения вступили в силу, нужно перезапустить KODI. Перезапустить?'

    from vdlib.kodi.sources import create_movies_and_tvshows
    if create_movies_and_tvshows(base_path, 
                                 scrapper='metadata.themoviedb.org.python', 
                                 scrapper_tv='metadata.tvshows.themoviedb.org.python', 
                                 suffix=' - TorrSpy'):
        
        if Dialog().yesno(addon_title(), restart_msg):
            executebuiltin('Quit')

def end_playback(player_video_info_str):
    pvi = PlayerVideoInfo(None)
    pvi.loads(player_video_info_str)

    video_info  = pvi.video_info
    play_url    = pvi.play_url
    sort_index  = pvi.sort_index

    if not video_info:
        log('video_info does not exists')
        return

    if video_info.get('dbid', 0) > 0:
        log('media already in medialibrary')
        return

    if pvi.time and pvi.total_time:
        percent = pvi.time / pvi.total_time * 100
        log('percent is {}'.format(percent))
        log('pvi.time is {}'.format(pvi.time))

        if pvi.media_type == 'movie':
            if pvi.time >= 180 and percent < 90: 
                save_movie(pvi)
        elif pvi.media_type == 'tvshow':
            if pvi.time >= 180:
                #import vsdbg
                #vsdbg.breakpoint()
                save_tvshow(pvi)

        log("media_type = '{}'".format(pvi.media_type))

def get_hash(item):
    return item.get('Hash', item['hash'])

def get_mem_setting(key):
    try:
        import xbmcgui
        window = xbmcgui.Window(10000)
        value = window.getProperty(key)
        log(u'{} is {}'.format(key, value))
        return value
    except AttributeError:
        return addon_setting(key)

def set_mem_setting(key, value):
    try:
        import xbmcgui
        window = xbmcgui.Window(10000)
        window.setProperty(key, value)
        #log('{} set to {}'.format(key, value))
    except AttributeError:
        addon_set_setting(key, value)

class ProcessedItems(object):
    def __init__(self):
        self.items = []
        self.path = make_path_to_base_relative('.data/processed_items.json')

    def load(self):
        import errno
        try:
            if filesystem.exists(self.path):
                with filesystem.fopen(self.path, 'r') as f:
                    self.items = json.load(f)
        #except FileNotFoundError:
        except EnvironmentError as e:
            if e.errno != errno.ENOENT:
                raise
        self.time_touch()

    def save(self):
        with filesystem.fopen(self.path, 'w') as f:
            json.dump(self.items, f)
        self.time_touch()

    def time_touch(self):
        set_mem_setting('torrspy_processed_time', str(time()))

    def is_time_expired(self):
        t = get_mem_setting('torrspy_processed_time')
        try:
            t = float(t)
            return time() > t + 1 * MINUTES
        except ValueError:
            return True

    def is_processed(self, list_item):
        # type: (dict) -> bool
        self.time_touch()
        for item in self.items:
            if get_hash(item) == get_hash(list_item):
                if 'next_attempt' in item:
                    return time() < item.get('next_attempt')
                return True
        return False

    def set_processed(self, list_item, timeout=None):
        # type: (dict, float) -> bool
        data = list_item.v2 if hasattr(list_item, 'v2') else list_item
        if timeout:
            data['next_attempt'] = time() + timeout

        self.items = [ item for item in self.items if get_hash(item) != get_hash(list_item) ]
        self.items.append(data)
        self.time_touch()
        return timeout==None


def try_append_torrent_to_media_library(list_item, engine, processed_items):
    # type: (dict, Engine, ProcessedItems) -> bool
    if processed_items.is_processed(list_item):
        return False

    hash = list_item['Hash']
    engine.hash = hash

    log('Getting files list')
    for n in range(20):
        try:
            ts = engine.torrent_stat()
            if 'Files' in ts:
                log("Files list exists")
                break
        except requests.exceptions.ConnectionError:
            pass
        sleep(1)
        processed_items.time_touch()

    if 'Files' not in ts:
        log("Files list does't exists!!!")
        return processed_items.set_processed(list_item, 1 * HOURS)

    data = list_item.get('data', list_item.get('Info'))
    if data:
        video_info = get_video_info_from_engine(engine, data)
    
    if not video_info:
        title = list_item.get('title')
        if not title:
            return processed_items.set_processed(list_item, 1 * DAYS)
        video_info = extract_original_title_year(title) if title else {}
        #update_video_info(video_info)

    if not video_info:
        video_info = load_video_info(hash)

    needed_fields = set(['imdbnumber', 'mediatype', 'originaltitle'])
    def keys():
        return video_info.keys() if version_info >= (3, 0) else video_info.viewkeys()
    if needed_fields & keys() != needed_fields:
        update_video_info_from_tmdb(video_info)
        if needed_fields & keys() != needed_fields:
            return processed_items.set_processed(list_item, 1 * DAYS)

    save_video_info(hash, video_info)

    for n in range(5):
        try:        
            if video_info['mediatype'] == 'movie':
                play_file = {}
                for file in engine.files(ts):
                    if file['size'] > play_file.get('size', 0) and is_video(file['path']):
                        play_file = file
                if play_file:
                    _, year = extract_title_date(play_file['path'])
                    if year and str(year) != str(video_info['year']):
                        return processed_items.set_processed(list_item, 1 * DAYS)                        

                    sort_index = play_file['file_id']
                    play_url = engine.play_url(sort_index, ts)
                    save_movie_strm(play_url, 
                                    sort_index, 
                                    original_title=video_info['originaltitle'], 
                                    year=video_info['year'])
                    return processed_items.set_processed(list_item)
            elif video_info['mediatype'] == 'tvshow':
                save_tvshow_strms(video_info.get('title'),
                                video_info.get('originaltitle'),
                                video_info.get('year'),
                                video_info.get('imdbnumber'),
                                engine,
                                ts_stat=ts)
                return processed_items.set_processed(list_item)

            return False
        except requests.exceptions.ConnectionError as e:
            pass

        print('Attempt #{}'.format(n+1+1))
        sleep(5)

def schedule_add_all_from_torserver():
    from vdlib.torrspy.info import add_all_from_torserver
    if add_all_from_torserver():
        processed_items = ProcessedItems()

        if not processed_items.is_time_expired():
            log('schedule_add_all_from_torserver: skipped by time')
            return

        processed_items.time_touch()
        log('schedule_add_all_from_torserver: processing...')
        add_all_from_processed_items(processed_items)
        log('schedule_add_all_from_torserver: processed')

def add_all_from_processed_items(processed_items):
    processed_items.load()
    engine = Engine(host=ts_settings.host, port=ts_settings.port, auth=ts_settings.auth)
    need_update = False
    for list_item in engine.list():
        need_update |= try_append_torrent_to_media_library(list_item, engine, processed_items)
    processed_items.save()

    if need_update:
        from xbmc import executebuiltin
        executebuiltin('UpdateLibrary("video")')

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
    elif arg_exists('end_playback', 1):
        end_playback(sys.argv[2])
    elif arg_exists('create_playlists', 1):
        create_playlists()
    elif arg_exists('create_sources', 1):
        create_sources()
    elif arg_exists('schedule_add_all_from_torserver', 1):
        schedule_add_all_from_torserver()
    else:
        open_settings()