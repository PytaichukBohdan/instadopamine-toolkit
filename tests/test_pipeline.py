import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from instadna.collect import discover, download_posts, embedded_context, profile_name, shortcode
from instadna.analyze import sample_times
from instadna.wiki import lint_wiki, lint_references
from instadna.site import safe_markdown, build_site


class InputTests(unittest.TestCase):
    def test_profile_url_is_scoped(self):
        self.assertEqual(profile_name("https://www.instagram.com/Example_Creator1/?igsh=test"),"example_creator1")
        for value in ["https://evil.example/test", "https://instagram.com.evil/test", "https://www.instagram.com/p/ABC/", "../x", "https://instagram.com/", "http://instagram.com/name"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                profile_name(value)

    def test_shortcode_rejects_arbitrary_network_target(self):
        self.assertEqual(shortcode("https://www.instagram.com/reel/Ab-c_1/"),"Ab-c_1")
        with self.assertRaises(ValueError):
            shortcode("http://127.0.0.1/p/secret/")

    def test_nested_embed_and_unicode(self):
        data={"gql_data":{"shortcode_media":{"caption":"Привіт \\\"світ\\\""}}}
        text='prefix "contextJSON":'+json.dumps(json.dumps(data))+' suffix'
        self.assertEqual(embedded_context(text),data)
        with self.assertRaises(ValueError):
            embedded_context("<html>Log in</html>")

    def test_pagination_exhaustion_does_not_mean_account_complete(self):
        responses=[json.dumps({"data":[{"url":"https://www.instagram.com/p/A/"}],"total":2,"hasMore":True}),
                   json.dumps({"data":[{"url":"https://www.instagram.com/p/B/"}],"total":2,"hasMore":False})]
        context={"context":{"posts_count":933,"graphql_media":[]}}
        def fake(url,**kwargs):
            if "instagram.com" in url:return '"contextJSON":'+json.dumps(json.dumps(context))
            if "rist.media" in url:return responses.pop(0)
            return ""
        with tempfile.TemporaryDirectory() as temp,patch("instadna.collect.fetch",side_effect=fake),patch("instadna.collect.time.sleep"):
            d=discover("test",Path(temp))
            self.assertEqual(len(d["posts"]),2)
            self.assertTrue(d["archive_exhausted"])
            self.assertFalse(d["account_complete"])
            self.assertEqual(d["profile_posts_reported"],933)

    def test_comment_links_are_not_discovered_as_profile_posts(self):
        context={"context":{"posts_count":10,"graphql_media":[]}}
        def fake(url,**kwargs):
            if "instagram.com" in url:return '"contextJSON":'+json.dumps(json.dumps(context))
            if "rist.media" in url:return json.dumps({"data":[],"hasMore":False})
            return '<!-- https://instagram.com/p/ADVERTISEMENT/ -->'
        with tempfile.TemporaryDirectory() as temp,patch("instadna.collect.fetch",side_effect=fake):
            self.assertEqual(discover("test",Path(temp))["posts"],[])

    def test_coauthor_header_is_accepted_but_caption_mention_is_not(self):
        for collaboration in [True,False]:
            with tempfile.TemporaryDirectory() as temp,patch("instadna.collect.fetch",return_value=b'x'*600),patch("instadna.collect.time.sleep"):
                root=Path(temp);folder=root/'posts'/'ABC';folder.mkdir(parents=True)
                (root/'manifest.json').write_text(json.dumps({"username":"test","posts":[{"shortcode":"ABC","url":"https://www.instagram.com/p/ABC/"}]}))
                (folder/'media.json').write_text(json.dumps({"owner":{"username":"other"},"display_url":"https://example.com/image.jpg","is_video":False}))
                (folder/'embed.html').write_text('<a class="CollabAvatar" href="https://www.instagram.com/test/">' if collaboration else '<p>@test</p>')
                d=download_posts(root,0)
                self.assertEqual(d['posts'][0]['status'],'downloaded' if collaboration else 'excluded_owner_mismatch')


class EvidenceTests(unittest.TestCase):
    def test_sampling_includes_opening_and_last_frame(self):
        times=sample_times(10.4,3)
        self.assertEqual(times,[0,0.5,1,2,3,6,9,10.3])
        self.assertTrue(all(0 <= t < .05 for t in sample_times(.05)))
        with self.assertRaises(ValueError):sample_times(10,0)

    def test_wiki_lint_finds_broken_and_escaping_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/"index.md").write_text("[Bad](missing.md) [Escape](../outside.md) [Web](https://example.com)")
            self.assertEqual(len(lint_wiki(root)),2)

    def test_raw_source_markup_cannot_execute(self):
        result=safe_markdown('<script>alert(1)</script>\n\n[click](javascript:alert(1))\n\n<img src=x onerror=alert(1)>')
        self.assertNotIn("<script",result)
        self.assertNotIn("javascript:",result)
        self.assertNotIn("onerror",result)

    def test_reference_locators_need_real_samples_and_correct_asset_type(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);wiki=root/"wiki";wiki.mkdir()
            frames=root/"posts"/"ABC"/"asset-00";frames.mkdir(parents=True)
            (frames/"frames.json").write_text(json.dumps({"kind":"video","frames":[{"seconds":0},{"seconds":3}]}))
            (wiki/"reference-brief.md").write_text("\n".join([
                "| [ABC](sources/ABC.md) | asset 0 @ 3.0s | valid |",
                "| [ABC](sources/ABC.md) | asset 0 @ 2.0s | never sampled |",
                "| [ABC](sources/ABC.md) | asset 0 still | wrong kind |",
                "| [ABC](sources/ABC.md) | asset 1 @ 0.0s | absent |",
            ]))
            errors=lint_references(wiki,root)
            self.assertEqual(len(errors),3)
            self.assertTrue(any("not sampled" in error for error in errors))

    def test_nonportable_wiki_links_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/"index.md").write_text("Read [[people.md]]")
            self.assertEqual(len(lint_wiki(root)),1)

    def test_publication_rejects_overlapping_or_nonempty_output(self):
        with tempfile.TemporaryDirectory() as temp:
            wiki=Path(temp)/"wiki";wiki.mkdir()
            with self.assertRaises(ValueError):build_site(wiki,wiki/"dist")
            out=Path(temp)/"dist";out.mkdir();(out/"secret.env").write_text("not for publication")
            with self.assertRaises(ValueError):build_site(wiki,out)

    def test_public_build_is_explicit_and_default_stays_protected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);wiki=root/"wiki";wiki.mkdir()
            (wiki/"index.md").write_text("# Creator DNA")
            (wiki/"coverage.json").write_text(json.dumps({"posts_analyzed":1,"videos_downloaded":1,"video_minutes_prepared":1,"profile_posts_reported":10}))
            (wiki/"source-inventory.json").write_text("[]")
            build_site(wiki,root/"protected")
            build_site(wiki,root/"public",public=True)
            self.assertIn("WWW-Authenticate",(root/"protected/_worker.js").read_text())
            self.assertNotIn("WWW-Authenticate",(root/"public/_worker.js").read_text())
            self.assertIn("CREATOR RESEARCH",(root/"public/index.html").read_text())


if __name__ == "__main__":
    unittest.main()
