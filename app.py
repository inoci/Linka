from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
import random
import string
import time
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///linka.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

def generate_unique_username(base_username):
    """Генерирует уникальный username, добавляя случайные символы"""
    username = base_username
    counter = 1
    
    while User.query.filter_by(username=username).first():
        # Добавляем случайные символы к username
        random_chars = ''.join(random.choices(string.ascii_lowercase + string.digits, k=3))
        username = f"{base_username}_{random_chars}"
        counter += 1
        
        # Защита от бесконечного цикла
        if counter > 100:
            username = f"{base_username}_{random.randint(1000, 9999)}"
            break
    
    return username

# Модель пользователя
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    bio = db.Column(db.Text)
    avatar = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# Модель поста
class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(200))  # Путь к изображению
    emoji = db.Column(db.String(10))   # Эмодзи
    location = db.Column(db.String(100))  # Координаты геолокации
    location_name = db.Column(db.String(200))  # Название места
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    likes = db.Column(db.Integer, default=0)
    
    user = db.relationship('User', backref=db.backref('posts', lazy=True))

# Модель комментария
class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    user = db.relationship('User', backref=db.backref('comments', lazy=True))
    post = db.relationship('Post', backref=db.backref('comments', lazy=True))

# Модель лайка
class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    # Уникальное ограничение: один пользователь может лайкнуть пост только один раз
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='unique_user_post_like'),)
    
    user = db.relationship('User', backref=db.backref('user_likes', lazy=True))
    post = db.relationship('Post', backref=db.backref('post_likes', lazy=True))

# Модель подписки
class Follow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    following_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    # Уникальное ограничение: нельзя подписаться на одного пользователя дважды
    __table_args__ = (db.UniqueConstraint('follower_id', 'following_id', name='unique_follow'),)
    
    # Отношения для подписчиков и подписок
    follower = db.relationship('User', foreign_keys=[follower_id], backref=db.backref('following', lazy=True))
    following = db.relationship('User', foreign_keys=[following_id], backref=db.backref('followers', lazy=True))

# Главная страница
@app.route('/')
def index():
    if 'user_id' in session:
        # Получаем посты только с существующими пользователями
        posts = Post.query.join(User).order_by(Post.created_at.desc()).all()
        
        # Получаем комментарии для каждого поста
        for post in posts:
            post.comments_list = Comment.query.filter_by(post_id=post.id).join(User).order_by(Comment.created_at.asc()).all()
        
        # Проверяем, какие посты лайкнул текущий пользователь
        user_liked_posts = set()
        for post in posts:
            like = Like.query.filter_by(user_id=session['user_id'], post_id=post.id).first()
            if like:
                user_liked_posts.add(post.id)
        
        return render_template('feed.html', posts=posts, user_liked_posts=user_liked_posts)
    return redirect(url_for('login'))

# Страница входа
@app.route('/login', methods=['GET', 'POST'])
def login():
    # Если пользователь уже авторизован, перенаправляем на рекламную страницу
    if 'user_id' in session:
        return redirect(url_for('reklama'))
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            # Обычный вход
            session['user_id'] = user.id
            session['username'] = user.username
            flash('Успешный вход!', 'success')
            return redirect(url_for('index'))
        elif not user:
            # Автоматическое создание аккаунта
            user = User(
                username=username,
                email=f"{username}@linka.local",  # Генерируем email
                first_name=username,
                last_name=""
            )
            user.set_password(password)
            
            db.session.add(user)
            db.session.commit()
            
            session['user_id'] = user.id
            session['username'] = user.username
            return redirect(url_for('index'))
        else:
            # Пароль неверный, но username существует - создаем новый аккаунт
            new_username = generate_unique_username(username)
            user = User(
                username=new_username,
                email=f"{new_username}@linka.local",
                first_name=username,  # Оригинальное имя как first_name
                last_name=""
            )
            user.set_password(password)
            
            db.session.add(user)
            db.session.commit()
            
            session['user_id'] = user.id
            session['username'] = user.username
            return redirect(url_for('index'))
    
    return render_template('login.html')

# Выход
@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('index'))

# Создание поста
@app.route('/post', methods=['POST'])
def create_post():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    content = request.form['content']
    if content.strip():
        # Получаем медиа данные из формы
        emoji = request.form.get('emoji', '')
        location = request.form.get('location', '')
        location_name = request.form.get('location_name', '')
        
        # Обработка изображения
        image_path = None
        if 'image' in request.files:
            image_file = request.files['image']
            if image_file and image_file.filename:
                # Создаем папку для изображений если её нет
                upload_folder = 'static/uploads'
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder)
                
                # Генерируем уникальное имя файла
                filename = f"{session['user_id']}_{int(time.time())}_{secure_filename(image_file.filename)}"
                image_path = os.path.join(upload_folder, filename)
                image_file.save(image_path)
                image_path = f"uploads/{filename}"  # Относительный путь для HTML
        
        post = Post(
            content=content,
            image=image_path,
            emoji=emoji,
            location=location,
            location_name=location_name,
            user_id=session['user_id']
        )
        db.session.add(post)
        db.session.commit()
        flash('Пост опубликован!', 'success')
    
    return redirect(url_for('index'))

# Лайк поста
@app.route('/like/<int:post_id>')
def like_post(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    post = Post.query.get_or_404(post_id)
    
    # Проверяем, не лайкал ли уже пользователь этот пост
    existing_like = Like.query.filter_by(user_id=session['user_id'], post_id=post_id).first()
    
    if existing_like:
        # Если лайк уже есть, убираем его (unlike)
        db.session.delete(existing_like)
        post.likes -= 1
        flash('Лайк убран', 'info')
    else:
        # Если лайка нет, добавляем новый
        new_like = Like(user_id=session['user_id'], post_id=post_id)
        db.session.add(new_like)
        post.likes += 1
        flash('Пост лайкнут!', 'success')
    
    db.session.commit()
    return redirect(url_for('index'))

# API для получения актуального состояния лайков (для AJAX)
@app.route('/api/post/<int:post_id>/likes')
def get_post_likes(post_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    post = Post.query.get_or_404(post_id)
    
    # Проверяем, лайкнул ли текущий пользователь этот пост
    user_liked = Like.query.filter_by(user_id=session['user_id'], post_id=post_id).first() is not None
    
    return jsonify({
        'post_id': post_id,
        'likes_count': post.likes,
        'user_liked': user_liked
    })

# Создание комментария
@app.route('/comment/<int:post_id>', methods=['POST'])
def create_comment(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    content = request.form['content']
    if content.strip():
        comment = Comment(content=content, user_id=session['user_id'], post_id=post_id)
        db.session.add(comment)
        db.session.commit()
        flash('Комментарий добавлен!', 'success')
    
    return redirect(url_for('index'))

# Удаление комментария
@app.route('/delete_comment/<int:comment_id>')
def delete_comment(comment_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    comment = Comment.query.get_or_404(comment_id)
    
    # Проверяем, что пользователь удаляет свой комментарий
    if comment.user_id != session['user_id']:
        flash('Вы можете удалить только свой комментарий', 'error')
        return redirect(url_for('index'))
    
    db.session.delete(comment)
    db.session.commit()
    flash('Комментарий удален', 'info')
    
    return redirect(url_for('index'))

# Шаринг поста
@app.route('/share/<int:post_id>')
def share_post(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    post = Post.query.get_or_404(post_id)
    
    # Создаем новый пост с ссылкой на оригинальный
    share_content = f"Поделился постом: {post.content[:100]}{'...' if len(post.content) > 100 else ''}"
    shared_post = Post(content=share_content, user_id=session['user_id'])
    
    db.session.add(shared_post)
    db.session.commit()
    
    flash('Пост поделен!', 'success')
    return redirect(url_for('index'))

# API для получения комментариев поста
@app.route('/api/post/<int:post_id>/comments')
def get_post_comments(post_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    post = Post.query.get_or_404(post_id)
    comments = Comment.query.filter_by(post_id=post_id).join(User).order_by(Comment.created_at.asc()).all()
    
    comments_data = []
    for comment in comments:
        comments_data.append({
            'id': comment.id,
            'content': comment.content,
            'username': comment.user.username,
            'user_id': comment.user_id,
            'created_at': comment.created_at.strftime('%d.%m.%Y %H:%M'),
            'can_delete': comment.user_id == session['user_id']
        })
    
    return jsonify(comments_data)

# API для получения статистики поста
@app.route('/api/post/<int:post_id>/stats')
def get_post_stats(post_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    post = Post.query.get_or_404(post_id)
    
    # Проверяем, лайкнул ли текущий пользователь этот пост
    user_liked = Like.query.filter_by(user_id=session['user_id'], post_id=post_id).first() is not None
    
    # Получаем количество комментариев
    comments_count = Comment.query.filter_by(post_id=post_id).count()
    
    return jsonify({
        'post_id': post_id,
        'likes_count': post.likes,
        'comments_count': comments_count,
        'user_liked': user_liked
    })

# Подписка на пользователя
@app.route('/follow/<username>')
def follow_user(username):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_to_follow = User.query.filter_by(username=username).first_or_404()
    
    # Нельзя подписаться на себя
    if user_to_follow.id == session['user_id']:
        flash('Вы не можете подписаться на себя', 'error')
        return redirect(url_for('profile', username=username))
    
    # Проверяем, не подписаны ли уже
    existing_follow = Follow.query.filter_by(
        follower_id=session['user_id'], 
        following_id=user_to_follow.id
    ).first()
    
    if existing_follow:
        # Если уже подписаны, отписываемся
        db.session.delete(existing_follow)
        flash(f'Вы отписались от {user_to_follow.first_name}', 'info')
    else:
        # Если не подписаны, подписываемся
        new_follow = Follow(follower_id=session['user_id'], following_id=user_to_follow.id)
        db.session.add(new_follow)
        flash(f'Вы подписались на {user_to_follow.first_name}', 'success')
    
    db.session.commit()
    return redirect(url_for('profile', username=username))

# Профиль пользователя
@app.route('/profile/<username>')
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    # Получаем посты только с существующими пользователями
    posts = Post.query.filter_by(user_id=user.id).join(User).order_by(Post.created_at.desc()).all()
    
    # Получаем комментарии для каждого поста
    for post in posts:
        post.comments_list = Comment.query.filter_by(post_id=post.id).join(User).order_by(Comment.created_at.asc()).all()
    
    # Проверяем, подписан ли текущий пользователь на этого пользователя
    is_following = False
    if 'user_id' in session:
        is_following = Follow.query.filter_by(
            follower_id=session['user_id'], 
            following_id=user.id
        ).first() is not None
    
    # Получаем количество подписчиков и подписок
    followers_count = Follow.query.filter_by(following_id=user.id).count()
    following_count = Follow.query.filter_by(follower_id=user.id).count()
    
    # Проверяем, какие посты лайкнул текущий пользователь
    user_liked_posts = set()
    if 'user_id' in session:
        for post in posts:
            like = Like.query.filter_by(user_id=session['user_id'], post_id=post.id).first()
            if like:
                user_liked_posts.add(post.id)
    
    return render_template('profile.html', 
                         user=user, 
                         posts=posts, 
                         is_following=is_following,
                         followers_count=followers_count,
                         following_count=following_count,
                         user_liked_posts=user_liked_posts)

# Редактирование профиля
@app.route('/profile/<username>/edit', methods=['GET', 'POST'])
def edit_profile(username):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = User.query.filter_by(username=username).first_or_404()
    
    # Проверяем, что пользователь редактирует свой профиль
    if user.id != session['user_id']:
        flash('Вы можете редактировать только свой профиль', 'error')
        return redirect(url_for('profile', username=username))
    
    if request.method == 'POST':
        # Обновляем данные профиля
        user.first_name = request.form['first_name']
        user.last_name = request.form['last_name']
        user.bio = request.form['bio']
        
        # Проверяем, не занят ли новый username
        new_username = request.form['username']
        if new_username != user.username:
            existing_user = User.query.filter_by(username=new_username).first()
            if existing_user and existing_user.id != user.id:
                flash('Этот username уже занят', 'error')
            else:
                user.username = new_username
                session['username'] = new_username
                flash('Профиль обновлен!', 'success')
                return redirect(url_for('profile', username=new_username))
        else:
            flash('Профиль обновлен!', 'success')
            return redirect(url_for('profile', username=user.username))
        
        db.session.commit()
    
    return render_template('edit_profile.html', user=user)

# Рекламная страница для авторизованных пользователей
@app.route('/reklama')
def reklama():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Рандомные заголовки и описания для страницы reklama
    headers = [
        "Будьте всегда с Линка на любых устройствах",
        "Линка - ваша социальная сеть везде",
        "Подключитесь к Линка с любого устройства",
        "Линка доступна на всех платформах",
        "Оставайтесь на связи с Линка всегда",
        "Линка - связь без границ",
        "Ваша Линка в кармане и на столе",
        "Линка - универсальная социальная сеть"
    ]
    
    descriptions = [
        "Ожидайте, мы делаем кроссплатформенность для каждых устройств",
        "Скоро Линка будет доступна на всех ваших любимых устройствах",
        "Мы работаем над тем, чтобы Линка была везде, где вы",
        "Кроссплатформенность - наш приоритет номер один",
        "Скоро вы сможете использовать Линка на любом устройстве",
        "Мы создаем единый опыт для всех платформ",
        "Линка станет доступной на всех ваших устройствах",
        "Кроссплатформенность - ключ к вашему комфорту"
    ]
    
    # Выбираем случайный заголовок и описание
    random_header = random.choice(headers)
    random_description = random.choice(descriptions)
    
    return render_template('reklama.html', header=random_header, description=random_description)

# Создание базы данных
def init_db():
    with app.app_context():
        db.create_all()
        print("База данных создана!")

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
