import os
from functools import wraps
from uuid import uuid4
from flask import (Flask, render_template, request, redirect, url_for, session,
                   flash, abort, jsonify, send_from_directory)
from neo4j import GraphDatabase
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.join(BASE, 'media')

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'change-me')
driver = GraphDatabase.driver(
    os.getenv('NEO4J_URI', 'bolt://localhost:7687'),
    auth=(os.getenv('NEO4J_USER', 'neo4j'), os.getenv('NEO4J_PASSWORD', '12345678')))

# ---- Үүрэг (холбоосын төрөл) -> Монгол нэр ----
ROLE_MN = {'ACTED_IN': 'Жүжигчин', 'DIRECTED': 'Найруулагч', 'WROTE': 'Зохиолч', 'PRODUCED': 'Продюсер'}
ROLE_PL = {'ACTED_IN': 'Жүжигчид', 'DIRECTED': 'Найруулагч', 'WROTE': 'Зохиолч', 'PRODUCED': 'Продюсер'}
SECTIONS = {'actors': ('ACTED_IN', 'Жүжигчид'), 'directors': ('DIRECTED', 'Найруулагч'),
            'writers': ('WROTE', 'Зохиолч'), 'producers': ('PRODUCED', 'Продюсер'),
            'critics': ('REVIEWED', 'Шүүмжлэгч')}
DONE = {'ACTED_IN': 'Тоглосон кинонууд', 'DIRECTED': 'Найруулсан кинонууд',
        'WROTE': 'Зохиол бичсэн кинонууд', 'PRODUCED': 'Продюсер хийсэн кинонууд',
        'REVIEWED': 'Шүүмжилсэн кинонууд'}
PLACEHOLDER = ("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='200' height='300'>"
               "<rect width='100%25' height='100%25' fill='%23dee2e6'/><text x='50%25' y='50%25' "
               "text-anchor='middle' fill='%23868e96' font-size='16'>No image</text></svg>")


def run(cypher, **kw):
    with driver.session() as s:
        return s.run(cypher, **kw).data()


def num(s):
    s = (s or '').strip()
    return int(s) if s.lstrip('-').isdigit() else None


def save_img(file, folder):
    """Зургийг server-т хадгалж, DB-д хадгалах замыг буцаана."""
    if not file or not file.filename:
        return None
    ext = file.filename.rsplit('.', 1)[-1].lower()
    if ext not in {'jpg', 'jpeg', 'png', 'webp', 'gif'}:
        return None
    name = f'{uuid4().hex}.{ext}'
    d = os.path.join(MEDIA, 'images', folder)
    os.makedirs(d, exist_ok=True)
    file.save(os.path.join(d, name))
    return f'images/{folder}/{name}'


def img_url(path):
    return url_for('media', f=path) if path else PLACEHOLDER


def need(role=None):
    def deco(fn):
        @wraps(fn)
        def w(*a, **k):
            u = session.get('user')
            if not u:
                return redirect(url_for('login', next=request.path))
            if role and u['role'] != role:
                abort(403)
            return fn(*a, **k)
        return w
    return deco


@app.context_processor
def ctx():
    return dict(user=session.get('user'), ROLE_MN=ROLE_MN, ROLE_PL=ROLE_PL,
                SECTIONS=SECTIONS, DONE=DONE, img_url=img_url)


@app.route('/media/<path:f>')
def media(f):
    return send_from_directory(MEDIA, f)


# ================= Нэвтрэх / Бүртгүүлэх =================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        r = run("MATCH (u:User {username:$n}) RETURN u.password AS pw, u.role AS role",
                n=request.form['username'].strip())
        if r and check_password_hash(r[0]['pw'], request.form['password']):
            session['user'] = {'username': request.form['username'].strip(), 'role': r[0]['role']}
            nxt = request.args.get('next', '')
            return redirect(nxt if nxt.startswith('/') and not nxt.startswith('//') else url_for('movies'))
        flash('Нэр эсвэл нууц үг буруу байна')
    return render_template('auth.html', mode='login')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        n, pw = request.form['username'].strip(), request.form['password']
        if not n or len(pw) < 4:
            flash('Нэр хоосон байж болохгүй, нууц үг 4-өөс дээш тэмдэгттэй байна')
        elif run("MATCH (u:User {username:$n}) RETURN u", n=n):
            flash('Энэ нэр бүртгэлтэй байна')
        else:
            run("CREATE (:User {username:$n, password:$h, role:'user'})", n=n, h=generate_password_hash(pw))
            flash('Амжилттай бүртгэгдлээ. Нэвтэрнэ үү.')
            return redirect(url_for('login'))
    return render_template('auth.html', mode='register')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ================= Кино =================
@app.route('/')
def index():
    return redirect(url_for('movies') if session.get('user') else url_for('login'))


@app.route('/movies')
def movies():
    t = request.args.get('q', '').strip()
    rows = run("""MATCH (m:Movie)
        WHERE toLower(m.title) CONTAINS toLower($t)
          AND ($y1 IS NULL OR m.released >= $y1) AND ($y2 IS NULL OR m.released <= $y2)
        RETURN m{.*} AS m ORDER BY m.title""",
               t=t, y1=num(request.args.get('y1')), y2=num(request.args.get('y2')))
    items = [dict(name=r['m']['title'], sub=f"огноо: {r['m'].get('released', '-')}", img=r['m'].get('image'),
                  url=url_for('movie', t=r['m']['title'])) for r in rows]
    return render_template('list.html', title='Кинонууд', items=items, lq='Киноны нэрээр хайх',
                           ly='Кино нээлт хийсэн он', ph='Киноны нэр', found='Кино олдлоо',
                           add=url_for('movie_form'))


@app.route('/movie/<path:t>')
def movie(t):
    rows = run("""MATCH (m:Movie {title:$t})
        OPTIONAL MATCH (p:Person)-[r]->(m) WHERE type(r) IN ['ACTED_IN','DIRECTED','WROTE','PRODUCED']
        RETURN m{.*} AS m, collect({name:p.name, rel:type(r), roles:r.roles}) AS crew""", t=t)
    if not rows:
        abort(404)
    crew = {k: [] for k in ROLE_PL}
    for c in rows[0]['crew']:
        if c['name']:
            crew[c['rel']].append(c)
    reviews = run("""MATCH (n)-[r:REVIEWED]->(:Movie {title:$t})
        RETURN coalesce(n.username, n.name) AS who, 'User' IN labels(n) AS isuser,
               r.rating AS rating, r.summary AS summary""", t=t)
    stat = run("MATCH (:User)-[r:REVIEWED]->(:Movie {title:$t}) RETURN avg(r.rating) AS avg, count(r) AS n", t=t)[0]
    u = session.get('user')
    mine = next((r for r in reviews if u and r['isuser'] and r['who'] == u['username']), None)
    return render_template('movie.html', m=rows[0]['m'], crew=crew, reviews=reviews, stat=stat, mine=mine)


@app.route('/admin/movie/new', methods=['GET', 'POST'])
@app.route('/admin/movie/edit/<path:t>', methods=['GET', 'POST'])
@need('admin')
def movie_form(t=None):
    old = {}
    if t:
        r = run("MATCH (m:Movie {title:$t}) RETURN m{.*} AS m", t=t)
        if not r:
            abort(404)
        old = r[0]['m']
    if request.method == 'POST':
        f = request.form
        title, img = f['title'].strip(), save_img(request.files.get('image'), 'movies')
        args = dict(title=title, rel=num(f.get('released')), tag=f.get('tagline', ''), img=img)
        if t:
            run("""MATCH (m:Movie {title:$t}) SET m.title=$title, m.released=$rel, m.tagline=$tag,
                   m.image=coalesce($img, m.image)""", t=t, **args)
        else:
            run("""MERGE (m:Movie {title:$title}) SET m.released=$rel, m.tagline=$tag,
                   m.image=coalesce($img, m.image)""", **args)
        flash('Хадгаллаа')
        return redirect(url_for('movie', t=title))
    fields = [('title', 'Киноны нэр', 'text', old.get('title', '')),
              ('released', 'Нээлт хийсэн он', 'number', old.get('released', '')),
              ('tagline', 'Уриа үг', 'text', old.get('tagline', '')),
              ('image', 'Постер зураг', 'file', '')]
    return render_template('form.html', title='Кино засах' if t else 'Кино нэмэх', fields=fields)


@app.route('/admin/movie/delete/<path:t>', methods=['POST'])
@need('admin')
def movie_delete(t):
    run("MATCH (m:Movie {title:$t}) DETACH DELETE m", t=t)
    flash('Кино устгагдлаа')
    return redirect(url_for('movies'))


@app.route('/review/<path:t>', methods=['POST'])
@need()
def review(t):
    rating = max(1, min(5, num(request.form.get('rating')) or 5))
    run("""MATCH (u:User {username:$u}), (m:Movie {title:$t})
        MERGE (u)-[r:REVIEWED]->(m) SET r.rating=$rating, r.summary=$s""",
        u=session['user']['username'], t=t, rating=rating, s=request.form.get('summary', '').strip())
    flash('Сэтгэгдэл хадгалагдлаа')
    return redirect(url_for('movie', t=t))


# ================= Хүмүүс =================
@app.route('/people/<sec>')
def people(sec):
    if sec not in SECTIONS:
        abort(404)
    rel, title = SECTIONS[sec]
    rows = run("""MATCH (p:Person)-[:%s]->(:Movie)
        WHERE toLower(p.name) CONTAINS toLower($q)
          AND ($y1 IS NULL OR p.born >= $y1) AND ($y2 IS NULL OR p.born <= $y2)
        WITH DISTINCT p RETURN p{.*} AS p ORDER BY p.name""" % rel,
               q=request.args.get('q', '').strip(), y1=num(request.args.get('y1')), y2=num(request.args.get('y2')))
    items = [dict(name=r['p']['name'], sub=f"төрсөн он: {r['p'].get('born', '-')}", img=r['p'].get('image'),
                  url=url_for('person', n=r['p']['name'])) for r in rows]
    return render_template('list.html', title=title, items=items, lq='Хүний нэрээр хайх',
                           ly='Төрсөн он', ph='Хүний нэр', found='хүн олдлоо', add=url_for('person_form'))


@app.route('/person/<path:n>')
def person(n):
    rows = run("MATCH (p:Person {name:$n}) RETURN p{.*} AS p", n=n)
    if not rows:
        abort(404)
    films = run("""MATCH (:Person {name:$n})-[r]->(m:Movie)
        RETURN type(r) AS rel, m.title AS title, m.released AS year, r.roles AS roles
        ORDER BY m.released""", n=n)
    groups = {k: [f for f in films if f['rel'] == k] for k in DONE}
    return render_template('person.html', p=rows[0]['p'], groups=groups)


@app.route('/admin/person/new', methods=['GET', 'POST'])
@app.route('/admin/person/edit/<path:n>', methods=['GET', 'POST'])
@need('admin')
def person_form(n=None):
    old = {}
    if n:
        r = run("MATCH (p:Person {name:$n}) RETURN p{.*} AS p", n=n)
        if not r:
            abort(404)
        old = r[0]['p']
    if request.method == 'POST':
        f = request.form
        name, img = f['name'].strip(), save_img(request.files.get('image'), 'people')
        args = dict(name=name, born=num(f.get('born')), img=img)
        if n:
            run("MATCH (p:Person {name:$n}) SET p.name=$name, p.born=$born, p.image=coalesce($img, p.image)", n=n, **args)
        else:
            run("MERGE (p:Person {name:$name}) SET p.born=$born, p.image=coalesce($img, p.image)", **args)
        flash('Хадгаллаа')
        return redirect(url_for('person', n=name))
    fields = [('name', 'Нэр', 'text', old.get('name', '')),
              ('born', 'Төрсөн он', 'number', old.get('born', '')),
              ('image', 'Зураг', 'file', '')]
    return render_template('form.html', title='Хүн засах' if n else 'Хүн нэмэх', fields=fields)


@app.route('/admin/person/delete/<path:n>', methods=['POST'])
@need('admin')
def person_delete(n):
    run("MATCH (p:Person {name:$n}) DETACH DELETE p", n=n)
    flash('Хүн устгагдлаа')
    return redirect(url_for('people', sec='actors'))


# ================= Кинонд гишүүн бүртгэх (Admin) =================
@app.route('/admin/crew', methods=['GET', 'POST'])
@need('admin')
def crew():
    if request.method == 'POST':
        f = request.form
        m, p, role = f['movie'].strip(), f['person'].strip(), f['role']
        if role not in ROLE_MN:
            abort(400)
        roles = [x.strip() for x in f.get('roles', '').split(',') if x.strip()] if role == 'ACTED_IN' else None
        r = run("""MATCH (p:Person {name:$p}), (m:Movie {title:$m})
            MERGE (p)-[r:%s]->(m) SET r.roles=$roles RETURN count(r) AS n""" % role, p=p, m=m, roles=roles)
        if r and r[0]['n']:
            flash(f'{p} - {ROLE_MN[role]} болгон бүртгэгдлээ')
            return redirect(url_for('movie', t=m))
        flash('Кино эсвэл хүн олдсонгүй. Жагсаалтаас сонгоно уу.')
    return render_template('crew.html')


@app.route('/admin/crew/remove', methods=['POST'])
@need('admin')
def crew_remove():
    f = request.form
    if f['rel'] not in ROLE_MN:
        abort(400)
    run("MATCH (:Person {name:$p})-[r:%s]->(:Movie {title:$m}) DELETE r" % f['rel'], p=f['person'], m=f['movie'])
    return redirect(url_for('movie', t=f['movie']))


# ================= Autocomplete API =================
@app.route('/api/movies')
def api_movies():
    r = run("MATCH (m:Movie) WHERE toLower(m.title) CONTAINS toLower($q) RETURN m.title AS x ORDER BY x LIMIT 10",
            q=request.args.get('q', ''))
    return jsonify([i['x'] for i in r])


@app.route('/api/people')
def api_people():
    r = run("MATCH (p:Person) WHERE toLower(p.name) CONTAINS toLower($q) RETURN p.name AS x ORDER BY x LIMIT 10",
            q=request.args.get('q', ''))
    return jsonify([i['x'] for i in r])


def init():
    """Анхны Admin хэрэглэгч үүсгэнэ (нэр: admin)."""
    run("MERGE (u:User {username:'admin'}) ON CREATE SET u.password=$h, u.role='admin'",
        h=generate_password_hash(os.getenv('ADMIN_PASSWORD', 'admin123')))


if __name__ == '__main__':
    init()
    app.run(debug=True)
