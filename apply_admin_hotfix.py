from pathlib import Path
import shutil, datetime, re, sys
root=Path(__file__).resolve().parent.parent
# Use current working directory by default, so file can be run from project root even when script lives elsewhere
root=Path.cwd()
app=root/'app.py'
login=root/'templates'/'login.html'
admin=root/'templates'/'admin_login.html'
if not all(p.exists() for p in [app,login,admin]):
    sys.exit('ERROR: Run this from harvest-pool root, containing app.py and templates/login.html and templates/admin_login.html. Nothing changed.')
a=app.read_text(encoding='utf-8')
l=login.read_text(encoding='utf-8')
t=admin.read_text(encoding='utf-8')
old="""    if current_user.is_authenticated:
        return redirect(url_for('admin_dashboard' if current_user.role=='admin' else 'dashboard'))
    if request.method == 'GET':
        return render_template('admin_login.html')"""
new="""    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        if request.method == 'GET':
            return render_template('admin_login.html', switch_account=True)
        flash('Sign out of your current account before signing in as administrator.', 'error')
        return redirect(url_for('admin_login'))
    if request.method == 'GET':
        return render_template('admin_login.html', switch_account=False)"""
if 'switch_account=True' not in a:
    start=a.find("@app.route('/admin/login'")
    end=a.find("@app.get('/admin')", start)
    if start<0 or end<0 or old not in a[start:end]:
        sys.exit('ERROR: Admin login route differs from expected Phase 12/13 version. Nothing changed. Share the admin_login route for a targeted fix.')
    a=a[:start]+a[start:end].replace(old,new,1)+a[end:]
if 'url_for(\'admin_login\')' not in l and 'url_for("admin_login")' not in l:
    marker='{% endblock %}'
    if marker not in l:
        sys.exit('ERROR: Login template marker not found. Nothing changed.')
    l=l.replace(marker,'<p class="auth-switch">Marketplace administrator? <a href="{{ url_for(\'admin_login\') }}">Administrator sign in</a></p>'+marker,1)
if 'switch_account' not in t:
    marker='<form method="post" class="modern-form">'
    if marker not in t:
        sys.exit('ERROR: Admin template form not found. Nothing changed.')
    ui='''{% if switch_account %}<div class="notice error" role="alert"><strong>You are signed in with another account.</strong> To switch to administration, sign out first.</div><form method="post" action="{{ url_for('logout') }}"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><button class="action-main full-width" type="submit">Sign out and switch account</button></form>{% else %}'''
    t=t.replace(marker,ui+marker,1)
    t=t.replace('</form><p class="auth-switch">','</form>{% endif %}<p class="auth-switch">',1)
# Verify Python syntax before any write
compile(a,str(app),'exec')
stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
b=root/'backups'/('admin_access_hotfix_'+stamp)
b.mkdir(parents=True,exist_ok=True)
for p in [app,login,admin]:
    target=b/p.relative_to(root)
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(p,target)
app.write_text(a,encoding='utf-8')
login.write_text(l,encoding='utf-8')
admin.write_text(t,encoding='utf-8')
print('Admin access hotfix applied. Original files backed up to:',b)
print('Restart Flask, visit /login, choose Administrator sign in. If already signed in, sign out first.')
