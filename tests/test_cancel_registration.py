"""取消报名接口测试。"""


def test_cancel_success(client, auth, event, registration):
    resp = client.put(f"/api/cancel_registration/{registration['registration_id']}",
                      headers=auth(registration['stu_token']))
    assert resp.status_code == 200
    assert resp.get_json()['code'] == 200


def test_cancel_twice_fails(client, auth, event, registration):
    rid = registration['registration_id']
    first = client.put(f'/api/cancel_registration/{rid}',
                       headers=auth(registration['stu_token']))
    assert first.status_code == 200

    second = client.put(f'/api/cancel_registration/{rid}',
                        headers=auth(registration['stu_token']))
    assert second.status_code == 400
    assert second.get_json()['code'] == 400


def test_cancel_by_other_student_forbidden(client, auth, event, registration, make_user):
    _, other_token = make_user('student')
    resp = client.put(f"/api/cancel_registration/{registration['registration_id']}",
                      headers=auth(other_token))
    assert resp.status_code == 403
    assert resp.get_json()['code'] == 403
