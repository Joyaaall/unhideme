import unittest
from backend import app

class MediaTests(unittest.TestCase):
    def test_direct_images_decode_preview_and_ignore_untrusted_hosts(self):
        extract = getattr(app, 'extract_images', None)
        self.assertTrue(callable(extract), 'image extraction is missing')
        row = {'url':'https://i.redd.it/photo.png','preview':{'images':[{'source':{'url':'https://preview.redd.it/photo.png?x=1&amp;y=2'},'resolutions':[{'width':640,'url':'https://preview.redd.it/photo.png?width=640&amp;x=1'}]}]}}
        images = extract(row)
        self.assertEqual(len(images),1)
        self.assertEqual(images[0]['url'],row['url'])
        self.assertEqual(images[0]['preview_url'],'https://preview.redd.it/photo.png?width=640&x=1')
        for url in ['http://i.redd.it/photo.png','https://i.redd.it.evil.com/photo.png','https://user@i.redd.it/photo.png','https://i.redd.it:443/photo.png','https://evil.com/photo.png','javascript:alert(1)','https://i.redd.it/a.svg']:
            self.assertEqual(extract({'url':url}),[])

    def test_gallery_order_cap_and_video_exclusion(self):
        extract = getattr(app, 'extract_images', None)
        self.assertTrue(callable(extract), 'image extraction is missing')
        row={'gallery_data':{'items':[{'media_id':'b'},{'media_id':'a'},{'media_id':'v'}]},'media_metadata':{'a':{'e':'Image','s':{'u':'https://preview.redd.it/a.png'}},'b':{'e':'Image','s':{'u':'https://preview.redd.it/b.jpg'}},'v':{'e':'RedditVideo','s':{'u':'https://preview.redd.it/v.jpg'}}}}
        self.assertEqual([x['url'] for x in extract(row)],['https://preview.redd.it/b.jpg','https://preview.redd.it/a.png'])
        row['gallery_data']['items']=[{'media_id':'a'}]*50
        self.assertEqual(len(extract(row)),1)
        self.assertEqual(extract({'is_video':True,'preview':{'images':[{'source':{'url':'https://preview.redd.it/x.jpg'}}]}}),[])

    def test_media_survives_normalization_merge_with_sensitive_flags(self):
        row={'id':'abc123','url':'https://reddit.com/r/test/comments/abc123/title/','author':'Example','_archive':True,'source':'arctic-shift','images':[{'url':'https://i.redd.it/photo.png','preview_url':'https://preview.redd.it/photo.png'}],'over_18':True,'spoiler':True}
        results=app.normalize_results([{**row,'images':[],'source':'pullpush','over_18':False,'spoiler':False},row],'Example','archive')
        self.assertEqual(len(results),1)
        self.assertEqual(len(results[0].get('images',[])),1,'dedupe discarded media')
        self.assertTrue(results[0]['over_18'])
        self.assertTrue(results[0]['spoiler'])

if __name__ == '__main__': unittest.main()
