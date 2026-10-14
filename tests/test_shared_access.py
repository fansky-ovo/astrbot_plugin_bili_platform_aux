import asyncio
import types
from unittest.mock import patch, AsyncMock
from .test_main_stub import PluginTestCase, _PLUGIN


class SharedAccessTests(PluginTestCase):
    def event(self, origin='qq:GroupMessage:123'):
        return types.SimpleNamespace(unified_msg_origin=origin, get_sender_id=lambda: 'u1')

    def save(self, shared=True, sid='shared-sid'):
        self.plugin.config.save_session('u1', platform_url='https://bilidyn.basmc.org',
                                        username='test', sid=sid, shared=shared)

    def test_empty_whitelist_denies_saved_shared(self):
        self.save()
        with self.assertRaises(_PLUGIN.PlatformAPIError):
            self.plugin._client(self.event())

    def test_exact_origin_only_and_revocation(self):
        self.save()
        self.plugin._conf['shared_session_whitelist'] = self.event().unified_msg_origin
        self.plugin._client(self.event())
        with self.assertRaises(_PLUGIN.PlatformAPIError):
            self.plugin._client(self.event('qq:FriendMessage:u1'))
        self.plugin._conf['shared_session_whitelist'] = ''
        with self.assertRaises(_PLUGIN.PlatformAPIError):
            self.plugin._client(self.event())

    def test_personal_session_allowed(self):
        self.save(False, 'personal-sid')
        self.plugin._client(self.event())

    def test_legacy_shared_sid_denied(self):
        self.plugin._conf['sid'] = 'shared-sid'
        self.save(False)
        with self.assertRaises(_PLUGIN.PlatformAPIError):
            self.plugin._client(self.event())

    def test_bootstrap_denied_without_network(self):
        self.plugin._conf['sid'] = 'shared-sid'
        with patch.object(_PLUGIN, 'BiliPlatformClient') as client:
            asyncio.run(self.plugin._bootstrap_from_env(self.event()))
            client.assert_not_called()
        self.assertIsNone(self.plugin.config.load_session('u1'))

    def test_bootstrap_marks_shared(self):
        self.plugin._conf.update(sid='shared-sid', shared_session_whitelist=self.event().unified_msg_origin)
        with patch.object(_PLUGIN, 'BiliPlatformClient') as client:
            client.return_value.me = AsyncMock(return_value={'username':'test'})
            asyncio.run(self.plugin._bootstrap_from_env(self.event()))
        self.assertTrue(self.plugin.config.load_session('u1')['shared'])

    def test_revoked_notifications_skip_network(self):
        self.save()
        self.plugin.config.set_origin('u1', self.event().unified_msg_origin)
        with patch.object(_PLUGIN, 'BiliPlatformClient') as client:
            asyncio.run(self.plugin._poll_notifications('u1'))
            client.assert_not_called()

    def test_llm_denied_before_read(self):
        self.save()
        async def run():
            return [item async for item in self.plugin.llm_accounts(self.event())]
        with patch.object(self.plugin, '_accounts') as accounts:
            result = asyncio.run(run())
            accounts.assert_not_called()
        self.assertIn('白名单', result[0])
