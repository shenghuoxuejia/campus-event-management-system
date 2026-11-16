"""评论接口测试。"""


def test_post_and_get_comment(client, auth, event, make_user):
    _, stu_token = make_user('student')
    resp = client.post('/api/comments', headers=auth(stu_token), json={
        'event_id': event['event_id'], 'content': '这个活动真不错！',
    })
    assert resp.status_code == 200
    assert resp.get_json()['code'] == 200

    comments = client.get(f"/api/comments/{event['event_id']}",
                          headers=auth(stu_token)).get_json()['data']
    assert any(c['content'] == '这个活动真不错！' for c in comments)


def test_post_comment_empty_fails(client, auth, event, make_user):
    _, stu_token = make_user('student')
    resp = client.post('/api/comments', headers=auth(stu_token), json={
        'event_id': event['event_id'], 'content': '   ',
    })
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 400


def test_post_comment_too_long_fails(client, auth, event, make_user):
    _, stu_token = make_user('student')
    resp = client.post('/api/comments', headers=auth(stu_token), json={
        'event_id': event['event_id'], 'content': '长' * 501,
    })
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 400


def test_post_comment_nonexistent_event_fails(client, auth, make_user):
    _, stu_token = make_user('student')
    resp = client.post('/api/comments', headers=auth(stu_token), json={
        'event_id': 999999, 'content': '评论',
    })
    assert resp.status_code == 404
    assert resp.get_json()['code'] == 404
