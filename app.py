from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import random
import string
import time
from datetime import datetime, timedelta
import re
from functools import wraps

app = Flask(__name__)
app.config['SECRET_KEY'] = '21fA1h2GhFk'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///linka.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Сессия сохраняется между перезапусками браузера
app.config['SESSION_COOKIE_NAME'] = 'linka_session'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=90)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False  # включите True при работе по HTTPS

# Настройки для загрузки файлов
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'webm', 'mov'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

db = SQLAlchemy(app)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def apply_comment_filters(comment_content, community):
    """Применяет фильтры комментариев сообщества"""
    if not community.comments_enabled:
        return False, "Комментарии запрещены в этом сообществе"
    
    # Фильтр нецензурных выражений
    if community.profanity_filter:
        profanity_words = ['мат', 'ругательство', 'плохое_слово']  # Здесь можно подключить API для проверки
        if any(word in comment_content.lower() for word in profanity_words):
            return False, "Комментарий содержит нецензурные выражения"
    
    # Фильтр враждебных высказываний
    if community.hostile_filter:
        hostile_patterns = ['ненавижу', 'убей', 'смерть', 'уничтожь']
        if any(pattern in comment_content.lower() for pattern in hostile_patterns):
            return False, "Комментарий содержит враждебные высказывания"
    
    # Фильтр по ключевым словам
    if community.keyword_filter and community.banned_keywords:
        banned_words = [word.strip().lower() for word in community.banned_keywords.split(',')]
        if any(word in comment_content.lower() for word in banned_words):
            return False, "Комментарий содержит запрещенные слова"
    
    return True, "OK"

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

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function

# Модель пользователя
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    bio = db.Column(db.Text)
    avatar = db.Column(db.String(200))
    status = db.Column(db.String(100))  # Статус профиля
    is_online = db.Column(db.Boolean, default=False)  # Онлайн статус
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)  # Последняя активность
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    # Антиспам поля
    comment_count_today = db.Column(db.Integer, default=0)  # Количество комментариев сегодня
    last_comment_time = db.Column(db.DateTime)  # Время последнего комментария
    is_banned = db.Column(db.Boolean, default=False)  # Бан за спам
    like_cooldown = db.Column(db.DateTime)  # Кулдаун для лайков пользователя

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def update_last_seen(self):
        self.last_seen = datetime.utcnow()
        self.is_online = True
        db.session.commit()
    
    def check_spam_protection(self):
        """Проверяет защиту от спама"""
        now = datetime.utcnow()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Сброс счетчика комментариев в новый день
        if self.last_comment_time and self.last_comment_time < today:
            self.comment_count_today = 0
        
        # Проверка лимита комментариев (максимум 50 в день)
        if self.comment_count_today >= 50:
            return False, "Превышен лимит комментариев на сегодня"
        
        # Проверка времени между комментариями (минимум 10 секунд)
        if self.last_comment_time and (now - self.last_comment_time).total_seconds() < 10:
            return False, "Слишком часто комментируете. Подождите немного."
        
        return True, "OK"

# Модель поста
class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(200))  # Путь к изображению
    video = db.Column(db.String(200))  # Путь к видео
    emoji = db.Column(db.String(10))   # Эмодзи
    location = db.Column(db.String(100))  # Координаты геолокации
    location_name = db.Column(db.String(200))  # Название места
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    community_id = db.Column(db.Integer, db.ForeignKey('community.id', ondelete='CASCADE'), nullable=True)  # Пост может быть в сообществе
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    likes = db.Column(db.Integer, default=0)
    
    # Новые поля
    visibility = db.Column(db.String(20), default='public')  # public, friends, private
    category = db.Column(db.String(50))  # Категория поста
    tags = db.Column(db.Text)  # Теги через запятую
    
    # Защита от накрутки
    like_cooldown = db.Column(db.DateTime)  # Кулдаун для лайков
    repost_cooldown = db.Column(db.DateTime)  # Кулдаун для репостов
    
    # Связи
    user = db.relationship('User', backref=db.backref('posts', lazy=True))
    community = db.relationship('Community', backref=db.backref('community_posts', lazy=True))
    
    @property
    def comments_list(self):
        """Возвращает список комментариев к посту"""
        return Comment.query.filter_by(post_id=self.id).join(User).order_by(Comment.created_at.asc()).all()
    
    def get_tags_list(self):
        """Возвращает список тегов"""
        if self.tags:
            return [tag.strip() for tag in self.tags.split(',')]
        return []
    
    def add_tag(self, tag):
        """Добавляет тег к посту"""
        tags_list = self.get_tags_list()
        if tag not in tags_list:
            tags_list.append(tag)
            self.tags = ', '.join(tags_list)
    
    def can_be_liked_by(self, user_id):
        """Проверяет, может ли пользователь лайкнуть пост"""
        if not self.like_cooldown:
            return True
        
        now = datetime.utcnow()
        if now > self.like_cooldown:
            return True
        
        return False
    
    def can_be_reposted_by(self, user_id):
        """Проверяет, может ли пользователь репостить пост"""
        if not self.repost_cooldown:
            return True
        
        now = datetime.utcnow()
        if now > self.repost_cooldown:
            return True
        
        return False

# Модель комментария
class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    # Антиспам поля
    is_spam = db.Column(db.Boolean, default=False)
    spam_score = db.Column(db.Float, default=0.0)  # Оценка спама
    
    user = db.relationship('User', backref=db.backref('comments', lazy=True))
    post = db.relationship('Post', backref=db.backref('comments', lazy=True))
    
    def check_spam(self):
        """Проверяет комментарий на спам"""
        content = self.content.lower()
        spam_words = ['спам', 'реклама', 'купить', 'продать', 'http://', 'https://']
        spam_score = 0
        
        # Проверка на спам-слова
        for word in spam_words:
            if word in content:
                spam_score += 0.3
        
        # Проверка на повторяющиеся символы
        if re.search(r'(.)\1{5,}', content):
            spam_score += 0.4
        
        # Проверка на капс
        if len(content) > 10 and content.isupper():
            spam_score += 0.3
        
        # Проверка на ссылки
        if re.search(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', content):
            spam_score += 0.5
        
        self.spam_score = spam_score
        self.is_spam = spam_score > 0.7
        
        return self.is_spam

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

# Модель реакций (новые эмоции)
class Reaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id', ondelete='CASCADE'), nullable=False)
    reaction_type = db.Column(db.String(20), nullable=False)  # like, laugh, surprise, sad, love, angry
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    # Уникальное ограничение: один пользователь может поставить одну реакцию на пост
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='unique_user_post_reaction'),)
    
    user = db.relationship('User', backref=db.backref('user_reactions', lazy=True))
    post = db.relationship('Post', backref=db.backref('post_reactions', lazy=True))

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

# Модель репоста
class Repost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    original_post_id = db.Column(db.Integer, db.ForeignKey('post.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    # Уникальное ограничение: один пользователь может репостить пост только один раз
    __table_args__ = (db.UniqueConstraint('user_id', 'original_post_id', name='unique_user_post_repost'),)
    
    user = db.relationship('User', backref=db.backref('user_reposts', lazy=True))
    original_post = db.relationship('Post', foreign_keys=[original_post_id], backref=db.backref('reposts', lazy=True))

# Модель категорий
class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text)
    color = db.Column(db.String(7), default='#3498db')  # HEX цвет
    icon = db.Column(db.String(50))  # Иконка Font Awesome
    created_at = db.Column(db.DateTime, server_default=db.func.now())

# Модель тегов
class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    usage_count = db.Column(db.Integer, default=0)  # Количество использований
    created_at = db.Column(db.DateTime, server_default=db.func.now())

# Модель статусов пользователя
class UserStatus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    status_text = db.Column(db.String(200), nullable=False)
    status_type = db.Column(db.String(20), default='text')  # text, emoji, custom
    is_animated = db.Column(db.Boolean, default=False)  # Анимированный статус
    expires_at = db.Column(db.DateTime)  # Время истечения статуса
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    user = db.relationship('User', backref=db.backref('statuses', lazy=True))
    
    def is_expired(self):
        """Проверяет, истек ли статус"""
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at

# Модель для отслеживания активности пользователей
class UserActivity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    activity_type = db.Column(db.String(50), nullable=False)  # login, post, comment, like, follow
    ip_address = db.Column(db.String(45))  # IP адрес
    user_agent = db.Column(db.Text)  # User Agent браузера
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    user = db.relationship('User', backref=db.backref('activities', lazy=True))

# Модель для защиты от накрутки
class AntiSpam(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(45), nullable=False)
    action_type = db.Column(db.String(50), nullable=False)  # like, comment, follow, post
    count = db.Column(db.Integer, default=1)  # Количество действий
    first_action = db.Column(db.DateTime, server_default=db.func.now())
    last_action = db.Column(db.DateTime, server_default=db.func.now())
    is_blocked = db.Column(db.Boolean, default=False)
    
    def check_rate_limit(self, max_actions, time_window_minutes):
        """Проверяет лимит действий"""
        now = datetime.utcnow()
        time_window = timedelta(minutes=time_window_minutes)
        
        # Если прошло время окна, сбрасываем счетчик
        if now - self.first_action > time_window:
            self.count = 1
            self.first_action = now
            self.last_action = now
            return True
        
        # Проверяем лимит
        if self.count >= max_actions:
            return False
        
        self.count += 1
        self.last_action = now
        return True

# Модель для историй (клипов)
class Story(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    media_type = db.Column(db.String(20), nullable=False)  # 'image', 'video'
    media_path = db.Column(db.String(200), nullable=False)
    caption = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, default=lambda: datetime.utcnow() + timedelta(hours=24))
    views_count = db.Column(db.Integer, default=0)
    
    # Связи
    user = db.relationship('User', backref='stories')
    views = db.relationship('StoryView', backref='story', cascade='all, delete-orphan')

# Модель для просмотров историй
class StoryView(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    story_id = db.Column(db.Integer, db.ForeignKey('story.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    viewed_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Уникальное ограничение - пользователь может просмотреть историю только один раз
    __table_args__ = (db.UniqueConstraint('story_id', 'user_id', name='_story_view_uc'),)

# Модель для сообществ
class Community(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    avatar = db.Column(db.String(255))  # Путь к аватару сообщества
    cover_image = db.Column(db.String(255))  # Путь к обложке
    category = db.Column(db.String(50))  # Категория сообщества
    is_private = db.Column(db.Boolean, default=False)  # Приватное/публичное
    website = db.Column(db.String(255))  # Сайт сообщества
    phone = db.Column(db.String(20))  # Телефон сообщества
    city = db.Column(db.String(100))  # Город сообщества
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Настройки дизайна
    color_scheme = db.Column(db.String(50), default='default')  # Цветовая схема
    font_size = db.Column(db.String(20), default='medium')  # Размер шрифта
    theme = db.Column(db.String(30), default='light')  # Тема (light/dark)
    custom_css = db.Column(db.Text)  # Пользовательский CSS
    
    # Настройки комментариев
    comments_enabled = db.Column(db.Boolean, default=True)  # Разрешены ли комментарии
    profanity_filter = db.Column(db.Boolean, default=False)  # Фильтр нецензурных выражений
    hostile_filter = db.Column(db.Boolean, default=False)  # Фильтр враждебных высказываний
    keyword_filter = db.Column(db.Boolean, default=False)  # Фильтр по ключевым словам
    banned_keywords = db.Column(db.Text)  # Запрещенные ключевые слова
    
    # Связи
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    posts = db.relationship('CommunityPost', backref='community', lazy='dynamic')
    
    def member_count(self):
        return CommunityMember.query.filter_by(community_id=self.id).count()
    
    def post_count(self):
        return self.posts.count()

# Модель для участников сообщества
class CommunityMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    community_id = db.Column(db.Integer, db.ForeignKey('community.id'), nullable=False)
    role = db.Column(db.String(20), default='member')  # member, moderator, admin
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Связи
    user = db.relationship('User', backref='community_memberships')
    community = db.relationship('Community', backref='members')
    
    # Уникальное ограничение: пользователь может быть участником сообщества только один раз
    __table_args__ = (db.UniqueConstraint('user_id', 'community_id'),)

# Модель для постов в сообществах
class CommunityPost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(255))
    video = db.Column(db.String(255))
    emoji = db.Column(db.String(10))
    location = db.Column(db.String(100))
    location_name = db.Column(db.String(100))
    visibility = db.Column(db.String(20), default='public')  # public, members_only
    category = db.Column(db.String(50))
    tags = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Связи
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    community_id = db.Column(db.Integer, db.ForeignKey('community.id'), nullable=False)
    likes = db.Column(db.Integer, default=0)
    comments = db.relationship('CommunityComment', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    
    def get_tags_list(self):
        if self.tags:
            return [tag.strip() for tag in self.tags.split(',')]
        return []

# Модель для комментариев в сообществах
class CommunityComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Связи
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('community_post.id'), nullable=False)

# Модель для лайков в сообществах
class CommunityLike(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('community_post.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Уникальное ограничение: пользователь может лайкнуть пост только один раз
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id'),)

# Главная страница
@app.route('/')
def feed():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Получаем все посты (обычные и из сообществ) с учетом видимости
    all_posts = []
    
    # Получаем обычные посты (не из сообществ)
    regular_posts = Post.query.filter(
        db.and_(
            Post.community_id.is_(None),  # Только посты НЕ из сообществ
            db.or_(
                Post.visibility == 'public',  # Публичные посты
                db.and_(
                    Post.visibility == 'friends',  # Посты для друзей
                    Post.user_id.in_(
                        db.session.query(Follow.following_id)
                        .filter(Follow.follower_id == session['user_id'])
                        .union(
                            db.session.query(Follow.follower_id)
                            .filter(Follow.following_id == session['user_id'])
                        )
                    )
                ),
                db.and_(
                    Post.visibility == 'private',  # Приватные посты только для автора
                    Post.user_id == session['user_id']
                )
            )
        )
    ).all()
    
    # Добавляем обычные посты
    for post in regular_posts:
        post.post_type = 'regular'
        # Убеждаемся, что у поста есть пользователь
        if not hasattr(post, 'user') or not post.user:
            post.user = User.query.get(post.user_id)
            if not post.user:
                continue
                
        # Получаем комментарии напрямую, не используя свойство
        post._comments_list = Comment.query.filter_by(post_id=post.id).join(User).order_by(Comment.created_at.asc()).all()
        # Убеждаемся, что у комментариев есть пользователи
        for comment in post._comments_list:
            if not hasattr(comment, 'user') or not comment.user:
                comment.user = User.query.get(comment.user_id)
                if not comment.user:
                    continue
                    
        # Фильтруем комментарии, где пользователь существует
        post._comments_list = [comment for comment in post._comments_list if comment.user is not None]
        
        # Получаем количество лайков для обычных постов (реальный подсчет)
        post.likes_count = Like.query.filter_by(post_id=post.id).count()
        # Проверяем, лайкнул ли пользователь этот пост
        post.user_liked = Like.query.filter_by(user_id=session['user_id'], post_id=post.id).first() is not None
        
        # Получаем детальные реакции для поста
        post.reactions = {
            'like': Reaction.query.filter_by(post_id=post.id, reaction_type='like').count(),
            'laugh': Reaction.query.filter_by(post_id=post.id, reaction_type='laugh').count(),
            'surprise': Reaction.query.filter_by(post_id=post.id, reaction_type='surprise').count(),
            'sad': Reaction.query.filter_by(post_id=post.id, reaction_type='sad').count(),
            'love': Reaction.query.filter_by(post_id=post.id, reaction_type='love').count(),
            'angry': Reaction.query.filter_by(post_id=post.id, reaction_type='angry').count()
        }
        
        all_posts.append(post)
    
    # Получаем посты из сообществ, где пользователь является участником
    user_communities = CommunityMember.query.filter_by(user_id=session['user_id']).all()
    for member in user_communities:
        community_posts = CommunityPost.query.filter_by(community_id=member.community_id).all()
        for post in community_posts:
            post.post_type = 'community'
            post.user = User.query.get(post.user_id)
            # Проверяем, существует ли пользователь
            if not post.user:
                continue
                
            post.community = Community.query.get(post.community_id)
            # Получаем комментарии для постов сообществ
            post._comments_list = CommunityComment.query.filter_by(post_id=post.id).order_by(CommunityComment.created_at.asc()).all()
            for comment in post._comments_list:
                comment.user = User.query.get(comment.user_id)
                # Проверяем, существует ли пользователь комментария
                if not comment.user:
                    continue
                    
            # Фильтруем комментарии, где пользователь существует
            post._comments_list = [comment for comment in post._comments_list if comment.user is not None]
            # Получаем количество лайков для постов сообществ
            post.likes_count = CommunityLike.query.filter_by(post_id=post.id).count()
            post.user_liked = CommunityLike.query.filter_by(
                user_id=session['user_id'], 
                post_id=post.id
            ).first() is not None
            
            # Получаем детальные реакции для поста сообщества
            post.reactions = {
                'like': Reaction.query.filter_by(post_id=post.id, reaction_type='like').count(),
                'laugh': Reaction.query.filter_by(post_id=post.id, reaction_type='laugh').count(),
                'surprise': Reaction.query.filter_by(post_id=post.id, reaction_type='surprise').count(),
                'sad': Reaction.query.filter_by(post_id=post.id, reaction_type='sad').count(),
                'love': Reaction.query.filter_by(post_id=post.id, reaction_type='love').count(),
                'angry': Reaction.query.filter_by(post_id=post.id, reaction_type='angry').count()
            }
            
            all_posts.append(post)
    
    # Сортируем все посты по дате создания (новые сначала)
    posts = sorted(all_posts, key=lambda x: x.created_at, reverse=True)
    
    # Получаем лайкнутые посты пользователя (только для обычных постов)
    user_liked_posts = [post.id for post in posts if post.post_type == 'regular' and post.id in [like.post_id for like in Like.query.filter_by(user_id=session['user_id']).all()]]

    # Предложения для подписки: пользователи, на которых еще не подписан текущий (3 случайных)
    followed_subq = db.session.query(Follow.following_id).filter(Follow.follower_id == session['user_id'])
    suggested_users = (User.query
                        .filter(User.id != session['user_id'])
                        .filter(~User.id.in_(followed_subq))
                        .order_by(db.func.random())
                        .limit(3)
                        .all())
    
    return render_template('feed.html', posts=posts, user_liked_posts=user_liked_posts, suggested_users=suggested_users)

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
            session.permanent = True
            session['avatar'] = user.avatar
            flash('Успешный вход!', 'success')
            return redirect(url_for('feed'))
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
            
            # Проверяем, что пользователь действительно создан
            if user.id:
                session['user_id'] = user.id
                session['username'] = user.username
                session.permanent = True
                session['avatar'] = user.avatar
                print(f"Создан новый пользователь: {username} с ID: {user.id}")
                return redirect(url_for('feed'))
            else:
                flash('Ошибка при создании аккаунта', 'error')
                return redirect(url_for('login'))
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
            
            # Проверяем, что пользователь действительно создан
            if user.id:
                session['user_id'] = user.id
                session['username'] = user.username
                session.permanent = True
                session['avatar'] = user.avatar
                print(f"Создан новый пользователь (пароль неверный): {new_username} с ID: {user.id}")
                return redirect(url_for('feed'))
            else:
                flash('Ошибка при создании аккаунта', 'error')
                return redirect(url_for('login'))
    
    return render_template('login.html')

# Выход
@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('feed'))

# Прямой endpoint с JSON ошибкой Unauthorized
@app.route('/unauthorized')
def unauthorized():
    return jsonify({"error": "Unauthorized", "success": False}), 401

# Создание поста
@app.route('/post', methods=['POST'])
def create_post():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:
        content = request.form.get('content', '').strip()
        if not content:
            flash('Пост не может быть пустым', 'error')
            return redirect(url_for('feed'))
        
        # Получаем медиа данные из формы
        emoji = request.form.get('emoji', '')
        location = request.form.get('location', '')
        location_name = request.form.get('location_name', '')
        visibility = request.form.get('visibility', 'public')
        category = request.form.get('category', '')
        tags = request.form.get('tags', '')
        
        # Обработка изображения
        image_path = None
        if 'image' in request.files:
            image_file = request.files['image']
            if image_file and image_file.filename:
                if not allowed_file(image_file.filename):
                    flash('Неподдерживаемый формат изображения. Разрешены: PNG, JPG, JPEG, GIF', 'error')
                    return redirect(url_for('feed'))
                
                try:
                    # Создаем папку для изображений если её нет
                    if not os.path.exists(UPLOAD_FOLDER):
                        os.makedirs(UPLOAD_FOLDER)
                    
                    # Генерируем уникальное имя файла
                    filename = f"{session['user_id']}_{int(time.time())}_{secure_filename(image_file.filename)}"
                    filepath = os.path.join(UPLOAD_FOLDER, filename)
                    
                    # Сохраняем файл
                    image_file.save(filepath)
                    
                    # Проверяем, что файл действительно сохранился
                    if not os.path.exists(filepath):
                        flash('Ошибка при сохранении изображения', 'error')
                        return redirect(url_for('feed'))
                    
                    image_path = f"uploads/{filename}"  # Относительный путь для HTML
                except Exception as e:
                    print(f"Ошибка при сохранении изображения: {str(e)}")
                    flash('Ошибка при загрузке изображения. Попробуйте еще раз.', 'error')
                    return redirect(url_for('feed'))
        
        # Обработка видео
        video_path = None
        if 'video' in request.files:
            video_file = request.files['video']
            if video_file and video_file.filename:
                if not allowed_file(video_file.filename):
                    flash('Неподдерживаемый формат видео. Разрешены: MP4, WEBM, MOV', 'error')
                    return redirect(url_for('feed'))
                
                try:
                    # Создаем папку для видео если её нет
                    if not os.path.exists(UPLOAD_FOLDER):
                        os.makedirs(UPLOAD_FOLDER)
                    
                    filename = f"{session['user_id']}_{int(time.time())}_{secure_filename(video_file.filename)}"
                    filepath = os.path.join(UPLOAD_FOLDER, filename)
                    
                    # Сохраняем файл
                    video_file.save(filepath)
                    
                    # Проверяем, что файл действительно сохранился
                    if not os.path.exists(filepath):
                        flash('Ошибка при сохранении видео', 'error')
                        return redirect(url_for('feed'))
                    
                    video_path = f"uploads/{filename}"
                except Exception as e:
                    print(f"Ошибка при сохранении видео: {str(e)}")
                    flash('Ошибка при загрузке видео. Попробуйте еще раз.', 'error')
                    return redirect(url_for('feed'))
        
        # Проверяем, создается ли пост в сообществе
        community_id = request.form.get('community_id')
        if community_id:
            try:
                community_id = int(community_id)
            except (ValueError, TypeError):
                community_id = None
        
        # Создаем пост
        try:
            post = Post(
                content=content,
                image=image_path,
                video=video_path,
                emoji=emoji,
                location=location,
                location_name=location_name,
                visibility=visibility,
                category=category,
                tags=tags,
                user_id=session['user_id'],
                community_id=community_id
            )
            db.session.add(post)
            db.session.commit()
            
            # Обновляем счетчики использования тегов
            if tags:
                try:
                    for tag_name in [tag.strip() for tag in tags.split(',')]:
                        if tag_name:  # Проверяем, что тег не пустой
                            tag = Tag.query.filter_by(name=tag_name).first()
                            if tag:
                                tag.usage_count += 1
                            else:
                                new_tag = Tag(name=tag_name, usage_count=1)
                                db.session.add(new_tag)
                    db.session.commit()
                except Exception as e:
                    print(f"Ошибка при обновлении тегов: {str(e)}")
                    # Не критичная ошибка, продолжаем
            
            flash('Пост опубликован!', 'success')
        except Exception as e:
            db.session.rollback()
            print(f"Ошибка при создании поста: {str(e)}")
            flash('Ошибка при публикации поста. Попробуйте еще раз.', 'error')
            return redirect(url_for('feed'))
    
    except Exception as e:
        print(f"Критическая ошибка при создании поста: {str(e)}")
        flash('Произошла ошибка при публикации поста. Попробуйте еще раз.', 'error')
    
    return redirect(url_for('feed'))

# Лайк поста (обновленная версия)
@app.route('/like_post/<int:post_id>', methods=['POST'])
def like_post(post_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    post = Post.query.get_or_404(post_id)
    
    # Проверяем, не лайкал ли уже пользователь этот пост
    existing_like = Like.query.filter_by(user_id=session['user_id'], post_id=post_id).first()
    
    if existing_like:
        # Если лайк уже есть, убираем его (unlike) - без кулдауна
        db.session.delete(existing_like)
        liked = False
    else:
        # Если лайка нет, проверяем защиту от накрутки только для новых лайков
        if not post.can_be_liked_by(session['user_id']):
            # Вычисляем, сколько времени осталось до снятия кулдауна
            if post.like_cooldown:
                remaining_time = (post.like_cooldown - datetime.utcnow()).total_seconds()
                if remaining_time > 0:
                    return jsonify({
                        'success': False, 
                        'error': f'Подождите {int(remaining_time)} секунд перед следующим лайком',
                        'cooldown_remaining': int(remaining_time)
                    }), 429
            
            return jsonify({'success': False, 'error': 'Слишком часто лайкаете. Подождите немного.'}), 429
        
        # Дополнительная проверка кулдауна пользователя
        user = User.query.get(session['user_id'])
        if user and user.like_cooldown:
            user_remaining_time = (user.like_cooldown - datetime.utcnow()).total_seconds()
            if user_remaining_time > 0:
                return jsonify({
                    'success': False, 
                    'error': f'Подождите {int(user_remaining_time)} секунд перед следующим лайком',
                    'cooldown_remaining': int(user_remaining_time)
                }), 429
        
        # Дополнительная защита от накрутки: проверяем количество лайков за последние 5 минут
        recent_likes = Like.query.filter(
            Like.user_id == session['user_id'],
            Like.created_at >= datetime.utcnow() - timedelta(minutes=5)
        ).count()
        
        if recent_likes >= 20:  # Максимум 20 лайков за 5 минут
            return jsonify({'success': False, 'error': 'Слишком много лайков. Подождите немного.'}), 429
        
        # Добавляем новый лайк
        new_like = Like(user_id=session['user_id'], post_id=post_id)
        db.session.add(new_like)
        liked = True
        
        # Устанавливаем кулдаун для лайков (3 секунды)
        post.like_cooldown = datetime.utcnow() + timedelta(seconds=3)
        
        # Также устанавливаем кулдаун для пользователя (чтобы не спамить)
        user = User.query.get(session['user_id'])
        if user:
            user.like_cooldown = datetime.utcnow() + timedelta(seconds=3)
    
    db.session.commit()
    
    # Получаем реальное количество лайков
    actual_likes_count = Like.query.filter_by(post_id=post_id).count()
    
    return jsonify({
        'success': True,
        'liked': liked,
        'likes_count': actual_likes_count
    })

# Новая система реакций
@app.route('/reaction/<int:post_id>', methods=['POST'])
def add_reaction(post_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    post = Post.query.get_or_404(post_id)
    reaction_type = request.json.get('reaction_type', 'like')
    
    # Проверяем, не поставил ли уже пользователь реакцию на этот пост
    existing_reaction = Reaction.query.filter_by(
        user_id=session['user_id'], 
        post_id=post_id
    ).first()
    
    if existing_reaction:
        if existing_reaction.reaction_type == reaction_type:
            # Если та же реакция, убираем её
            db.session.delete(existing_reaction)
            db.session.commit()
            return jsonify({
                'success': True,
                'reaction_removed': True,
                'reaction_type': reaction_type
            })
        else:
            # Если другая реакция, меняем на новую
            existing_reaction.reaction_type = reaction_type
    else:
        # Добавляем новую реакцию
        new_reaction = Reaction(
            user_id=session['user_id'],
            post_id=post_id,
            reaction_type=reaction_type
        )
        db.session.add(new_reaction)
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'reaction_type': reaction_type
    })

# Сброс кулдауна пользователя
@app.route('/api/reset-cooldown', methods=['POST'])
def reset_cooldown():
    try:
        if 'user_id' not in session:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401
        
        user = User.query.get(session['user_id'])
        if user:
            user.like_cooldown = None
            db.session.commit()
            return jsonify({'success': True, 'message': 'Кулдаун сброшен'})
        
        return jsonify({'success': False, 'error': 'Пользователь не найден'}), 404
    except Exception as e:
        print(f"Ошибка при сбросе кулдауна: {str(e)}")
        return jsonify({'success': False, 'error': 'Ошибка сервера'}), 500

# Получение настроек дизайна сообщества
@app.route('/api/community/<int:community_id>/design_settings')
def get_community_design_settings(community_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        community = Community.query.get_or_404(community_id)
        
        # Проверяем, что пользователь является участником сообщества
        member = CommunityMember.query.filter_by(
            user_id=session['user_id'], 
            community_id=community_id
        ).first()
        
        if not member:
            return jsonify({'error': 'Вы не являетесь участником этого сообщества'}), 403
        
        return jsonify({
            'success': True,
            'design_settings': {
                'color_scheme': community.color_scheme or 'default',
                'font_size': community.font_size or 'medium',
                'theme': community.theme or 'light',
                'custom_css': community.custom_css or ''
            }
        })
        
    except Exception as e:
        return jsonify({'error': f'Ошибка при получении настроек: {str(e)}'}), 500

# Применение настроек дизайна сообщества
@app.route('/apply_design_settings', methods=['POST'])
def apply_design_settings():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        data = request.json
        community_id = data.get('community_id')
        design_settings = data.get('design_settings', {})
        
        # Проверяем, что сообщество существует
        community = Community.query.get_or_404(community_id)
        
        # Проверяем, что пользователь является администратором сообщества
        if community.creator_id != session['user_id']:
            return jsonify({'success': False, 'error': 'Только администратор может применять настройки дизайна'}), 403
        
        # Применяем настройки дизайна
        if 'color_scheme' in design_settings:
            community.color_scheme = design_settings['color_scheme']
        
        if 'font_size' in design_settings:
            community.font_size = design_settings['font_size']
        
        if 'theme' in design_settings:
            community.theme = design_settings['theme']
        
        if 'custom_css' in design_settings:
            community.custom_css = design_settings['custom_css']
        
        # Обновляем время изменения
        community.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': 'Настройки дизайна применены',
            'design_settings': design_settings
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Ошибка при применении настроек: {str(e)}'}), 500

# Сброс настроек дизайна сообщества к значениям по умолчанию
@app.route('/reset_design_settings', methods=['POST'])
def reset_design_settings():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        data = request.json
        community_id = data.get('community_id')
        
        # Проверяем, что сообщество существует
        community = Community.query.get_or_404(community_id)
        
        # Проверяем, что пользователь является администратором сообщества
        if community.creator_id != session['user_id']:
            return jsonify({'success': False, 'error': 'Только администратор может сбрасывать настройки дизайна'}), 403
        
        # Сбрасываем настройки дизайна к значениям по умолчанию
        community.color_scheme = 'default'
        community.font_size = 'medium'
        community.theme = 'light'
        community.custom_css = None
        
        # Обновляем время изменения
        community.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': 'Настройки дизайна сброшены к значениям по умолчанию'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Ошибка при сбросе настроек: {str(e)}'}), 500

# Предварительный просмотр настроек дизайна сообщества
@app.route('/preview_design_settings', methods=['POST'])
def preview_design_settings():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        data = request.json
        community_id = data.get('community_id')
        design_settings = data.get('design_settings', {})
        
        # Проверяем, что сообщество существует
        community = Community.query.get_or_404(community_id)
        
        # Проверяем, что пользователь является участником сообщества
        member = CommunityMember.query.filter_by(
            user_id=session['user_id'], 
            community_id=community_id
        ).first()
        
        if not member:
            return jsonify({'error': 'Вы не являетесь участником этого сообщества'}), 403
        
        # Возвращаем настройки для предварительного просмотра
        return jsonify({
            'success': True,
            'preview_settings': {
                'color_scheme': design_settings.get('color_scheme', community.color_scheme or 'default'),
                'font_size': design_settings.get('font_size', community.font_size or 'medium'),
                'theme': design_settings.get('theme', community.theme or 'light'),
                'custom_css': design_settings.get('custom_css', community.custom_css or '')
            }
        })
        
    except Exception as e:
        return jsonify({'error': f'Ошибка при предварительном просмотре: {str(e)}'}), 500

# Экспорт настроек дизайна сообщества
@app.route('/export_design_settings/<int:community_id>')
def export_design_settings(community_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        community = Community.query.get_or_404(community_id)
        
        # Проверяем, что пользователь является администратором сообщества
        if community.creator_id != session['user_id']:
            return jsonify({'error': 'Только администратор может экспортировать настройки дизайна'}), 403
        
        # Создаем JSON файл с настройками
        settings_data = {
            'community_name': community.name,
            'export_date': datetime.utcnow().isoformat(),
            'design_settings': {
                'color_scheme': community.color_scheme or 'default',
                'font_size': community.font_size or 'medium',
                'theme': community.theme or 'light',
                'custom_css': community.custom_css or ''
            }
        }
        
        # Возвращаем JSON файл для скачивания
        response = jsonify(settings_data)
        response.headers['Content-Disposition'] = f'attachment; filename="{community.name}_design_settings.json"'
        return response
        
    except Exception as e:
        return jsonify({'error': f'Ошибка при экспорте настроек: {str(e)}'}), 500

# Импорт настроек дизайна сообщества
@app.route('/import_design_settings', methods=['POST'])
def import_design_settings():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        data = request.json
        community_id = data.get('community_id')
        imported_settings = data.get('imported_settings', {})
        
        # Проверяем, что сообщество существует
        community = Community.query.get_or_404(community_id)
        
        # Проверяем, что пользователь является администратором сообщества
        if community.creator_id != session['user_id']:
            return jsonify({'success': False, 'error': 'Только администратор может импортировать настройки дизайна'}), 403
        
        # Проверяем структуру импортированных настроек
        if 'design_settings' not in imported_settings:
            return jsonify({'success': False, 'error': 'Неверный формат файла настроек'}), 400
        
        design_settings = imported_settings['design_settings']
        
        # Применяем импортированные настройки
        if 'color_scheme' in design_settings:
            community.color_scheme = design_settings['color_scheme']
        
        if 'font_size' in design_settings:
            community.font_size = design_settings['font_size']
        
        if 'theme' in design_settings:
            community.theme = design_settings['theme']
        
        if 'custom_css' in design_settings:
            community.custom_css = design_settings['custom_css']
        
        # Обновляем время изменения
        community.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': 'Настройки дизайна импортированы',
            'imported_settings': design_settings
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Ошибка при импорте настроек: {str(e)}'}), 500

# Статистика использования настроек дизайна
@app.route('/api/design_settings_stats')
def get_design_settings_stats():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        # Получаем статистику по цветовым схемам
        color_schemes = db.session.query(
            Community.color_scheme, 
            db.func.count(Community.id)
        ).group_by(Community.color_scheme).all()
        
        # Получаем статистику по размерам шрифтов
        font_sizes = db.session.query(
            Community.font_size, 
            db.func.count(Community.id)
        ).group_by(Community.font_size).all()
        
        # Получаем статистику по темам
        themes = db.session.query(
            Community.theme, 
            db.func.count(Community.id)
        ).group_by(Community.theme).all()
        
        # Получаем общее количество сообществ с кастомным CSS
        custom_css_count = Community.query.filter(
            Community.custom_css.isnot(None),
            Community.custom_css != ''
        ).count()
        
        return jsonify({
            'success': True,
            'stats': {
                'color_schemes': dict(color_schemes),
                'font_sizes': dict(font_sizes),
                'themes': dict(themes),
                'custom_css_count': custom_css_count,
                'total_communities': Community.query.count()
            }
        })
        
    except Exception as e:
        return jsonify({'error': f'Ошибка при получении статистики: {str(e)}'}), 500

# Сброс всех настроек дизайна (только для администраторов системы)
@app.route('/admin/reset_all_design_settings', methods=['POST'])
def reset_all_design_settings():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        # Проверяем, что пользователь является администратором системы
        user = User.query.get(session['user_id'])
        if not user or user.username != 'admin':  # Простая проверка на админа
            return jsonify({'success': False, 'error': 'Доступ запрещен. Только администраторы системы могут выполнять эту операцию'}), 403
        
        # Сбрасываем все настройки дизайна к значениям по умолчанию
        communities = Community.query.all()
        reset_count = 0
        
        for community in communities:
            community.color_scheme = 'default'
            community.font_size = 'medium'
            community.theme = 'light'
            community.custom_css = None
            community.updated_at = datetime.utcnow()
            reset_count += 1
        
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'Настройки дизайна сброшены для {reset_count} сообществ'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Ошибка при сбросе всех настроек: {str(e)}'}), 500

# Валидация CSS кода
@app.route('/validate_css', methods=['POST'])
def validate_css():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        data = request.json
        css_code = data.get('css_code', '')
        
        if not css_code.strip():
            return jsonify({
                'success': True,
                'valid': True,
                'message': 'CSS код пустой'
            })
        
        # Простая валидация CSS (можно расширить)
        validation_errors = []
        
        # Проверяем базовый синтаксис
        if css_code.count('{') != css_code.count('}'):
            validation_errors.append('Несоответствие количества открывающих и закрывающих скобок')
        
        if css_code.count('(') != css_code.count(')'):
            validation_errors.append('Несоответствие количества открывающих и закрывающих скобок')
        
        # Проверяем на потенциально опасные свойства
        dangerous_properties = ['javascript:', 'expression(', 'eval(', 'import', '@import']
        for prop in dangerous_properties:
            if prop.lower() in css_code.lower():
                validation_errors.append(f'Обнаружена потенциально опасная конструкция: {prop}')
        
        # Проверяем длину CSS
        if len(css_code) > 10000:  # Максимум 10KB
            validation_errors.append('CSS код слишком длинный (максимум 10KB)')
        
        if validation_errors:
            return jsonify({
                'success': True,
                'valid': False,
                'errors': validation_errors
            })
        else:
            return jsonify({
                'success': True,
                'valid': True,
                'message': 'CSS код прошел валидацию'
            })
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'Ошибка при валидации CSS: {str(e)}'}), 500

# История изменений настроек дизайна
@app.route('/api/community/<int:community_id>/design_history')
def get_design_history(community_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        community = Community.query.get_or_404(community_id)
        
        # Проверяем, что пользователь является администратором сообщества
        if community.creator_id != session['user_id']:
            return jsonify({'error': 'Только администратор может просматривать историю изменений'}), 403
        
        # Возвращаем информацию о последних изменениях
        history = {
            'last_updated': community.updated_at.isoformat() if community.updated_at else None,
            'created_at': community.created_at.isoformat() if community.created_at else None,
            'current_settings': {
                'color_scheme': community.color_scheme or 'default',
                'font_size': community.font_size or 'medium',
                'theme': community.theme or 'light',
                'has_custom_css': bool(community.custom_css)
            }
        }
        
        return jsonify({
            'success': True,
            'history': history
        })
        
    except Exception as e:
        return jsonify({'error': f'Ошибка при получении истории: {str(e)}'}), 500

# Сохранение настроек дизайна сообщества
@app.route('/save_design_settings', methods=['POST'])
def save_design_settings():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        data = request.json
        community_id = data.get('community_id')
        design_settings = data.get('design_settings', {})
        
        # Проверяем, что сообщество существует
        community = Community.query.get_or_404(community_id)
        
        # Проверяем, что пользователь является администратором сообщества
        if community.creator_id != session['user_id']:
            return jsonify({'success': False, 'error': 'Только администратор может изменять настройки дизайна'}), 403
        
        # Сохраняем настройки дизайна
        if 'color_scheme' in design_settings:
            community.color_scheme = design_settings['color_scheme']
        
        if 'font_size' in design_settings:
            community.font_size = design_settings['font_size']
        
        if 'theme' in design_settings:
            community.theme = design_settings['theme']
        
        if 'custom_css' in design_settings:
            community.custom_css = design_settings['custom_css']
        
        # Обновляем время изменения
        community.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': 'Настройки дизайна сохранены',
            'design_settings': design_settings
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Ошибка при сохранении настроек: {str(e)}'}), 500

# Получение реакций поста
@app.route('/api/post/<int:post_id>/reactions')
def get_post_reactions(post_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    post = Post.query.get_or_404(post_id)
    reactions = Reaction.query.filter_by(post_id=post_id).all()
    
    # Группируем реакции по типам
    reaction_counts = {}
    user_reaction = None
    
    for reaction in reactions:
        reaction_type = reaction.reaction_type
        if reaction_type not in reaction_counts:
            reaction_counts[reaction_type] = 0
        reaction_counts[reaction_type] += 1
        
        # Проверяем реакцию текущего пользователя
        if reaction.user_id == session['user_id']:
            user_reaction = reaction_type
    
    return jsonify({
        'post_id': post_id,
        'reaction_counts': reaction_counts,
        'user_reaction': user_reaction
    })

# Обновление статуса пользователя
@app.route('/status', methods=['POST'])
def update_status():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    status_text = request.json.get('status_text', '')
    status_type = request.json.get('status_type', 'text')
    is_animated = request.json.get('is_animated', False)
    expires_in_hours = request.json.get('expires_in_hours', 24)
    
    if not status_text.strip():
        return jsonify({'success': False, 'error': 'Статус не может быть пустым'}), 400
    
    # Создаем новый статус
    new_status = UserStatus(
        user_id=session['user_id'],
        status_text=status_text,
        status_type=status_type,
        is_animated=is_animated,
        expires_at=datetime.utcnow() + timedelta(hours=expires_in_hours)
    )
    
    db.session.add(new_status)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'status': status_text,
        'expires_at': new_status.expires_at.isoformat()
    })

# Получение статуса пользователя
@app.route('/api/user/<username>/status')
def get_user_status(username):
    user = User.query.filter_by(username=username).first_or_404()
    
    # Получаем активный статус
    active_status = UserStatus.query.filter_by(
        user_id=user.id
    ).filter(
        (UserStatus.expires_at > datetime.utcnow()) | (UserStatus.expires_at.is_(None))
    ).order_by(UserStatus.created_at.desc()).first()
    
    return jsonify({
        'username': username,
        'status': active_status.status_text if active_status else None,
        'status_type': active_status.status_type if active_status else None,
        'is_animated': active_status.is_animated if active_status else False,
        'is_online': user.is_online,
        'last_seen': user.last_seen.isoformat() if user.last_seen else None
    })

# Создание комментария (обновленная версия с антиспамом)
@app.route('/comment/<int:post_id>', methods=['POST'])
def create_comment(post_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    user = User.query.get(session['user_id'])
    content = request.json.get('content', '')
    
    if not content.strip():
        return jsonify({'success': False, 'error': 'Комментарий не может быть пустым'}), 400
    
    # Проверяем защиту от спама
    can_comment, message = user.check_spam_protection()
    if not can_comment:
        return jsonify({'success': False, 'error': message}), 429
    
    # Получаем пост для проверки сообщества
    post = Post.query.get(post_id)
    
    # Если пост в сообществе, применяем фильтры
    if post and post.community_id:
        community = Community.query.get(post.community_id)
        if community:
            is_allowed, message = apply_comment_filters(content, community)
            if not is_allowed:
                return jsonify({'success': False, 'error': message}), 400
    
    # Создаем комментарий
    comment = Comment(
        content=content,
        user_id=session['user_id'],
        post_id=post_id
    )
    
    # Проверяем на спам
    is_spam = comment.check_spam()
    
    if is_spam:
        return jsonify({'success': False, 'error': 'Комментарий помечен как спам'}), 400
    
    # Обновляем счетчики пользователя
    user.comment_count_today += 1
    user.last_comment_time = datetime.utcnow()
    
    db.session.add(comment)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'comment_id': comment.id,
        'content': comment.content,
        'created_at': comment.created_at.isoformat()
    })

# Удаление комментария
@app.route('/comment/<int:comment_id>', methods=['DELETE'])
def delete_comment(comment_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    comment = Comment.query.get_or_404(comment_id)
    
    # Проверяем, что пользователь может удалить комментарий
    if comment.user_id != session['user_id']:
        return jsonify({'success': False, 'error': 'Недостаточно прав'}), 403
    
    db.session.delete(comment)
    db.session.commit()
    
    return jsonify({'success': True})

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
    return redirect(url_for('feed'))

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

# Друзья (подписки текущего пользователя)
@app.route('/friends')
@login_required
def friends():
    followed_subq = db.session.query(Follow.following_id).filter(Follow.follower_id == session['user_id'])
    friends_users = User.query.filter(User.id.in_(followed_subq)).order_by(User.first_name.asc()).all()
    return render_template('friends.html', friends=friends_users)

# Профиль пользователя
@app.route('/profile/<username>')
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    # Получаем посты только с существующими пользователями
    posts = Post.query.filter_by(user_id=user.id).join(User).order_by(Post.created_at.desc()).all()
    
    # Получаем комментарии для каждого поста
    for post in posts:
        # Получаем комментарии для поста
        post._comments_list = Comment.query.filter_by(post_id=post.id).join(User).order_by(Comment.created_at.asc()).all()
        # Убеждаемся, что у поста есть пользователь
        if not hasattr(post, 'user') or not post.user:
            post.user = user
            
        # Убеждаемся, что у комментариев есть пользователи
        for comment in post._comments_list:
            if not hasattr(comment, 'user') or not comment.user:
                comment.user = User.query.get(comment.user_id)
                if not comment.user:
                    continue
    
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
    
    # Предложения для подписки (3 случайных)
    exclude_ids = [user.id]
    if 'user_id' in session:
        exclude_ids.append(session['user_id'])
        followed_subq = db.session.query(Follow.following_id).filter(Follow.follower_id == session['user_id'])
        suggested_users = (User.query
                            .filter(~User.id.in_(followed_subq))
                            .filter(~User.id.in_(exclude_ids))
                            .order_by(db.func.random())
                            .limit(3)
                            .all())
    else:
        suggested_users = (User.query
                            .filter(~User.id.in_(exclude_ids))
                            .order_by(db.func.random())
                            .limit(3)
                            .all())

    return render_template('profile.html', 
                         user=user, 
                         posts=posts, 
                         is_following=is_following,
                         followers_count=followers_count,
                         following_count=following_count,
                         user_liked_posts=user_liked_posts,
                         suggested_users=suggested_users)

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
        # Получаем данные из формы
        new_username = request.form['username'].strip()
        first_name = request.form['first_name'].strip()
        last_name = request.form['last_name'].strip()
        bio = request.form['bio'].strip()
        
        # Валидация username (только буквы, цифры, подчеркивания)
        import re
        if not re.match(r'^[a-zA-Z0-9_]+$', new_username):
            flash('Username может содержать только буквы, цифры и подчеркивания', 'error')
            return render_template('edit_profile.html', user=user)
        
        # Проверяем длину username
        if len(new_username) < 3 or len(new_username) > 30:
            flash('Username должен быть от 3 до 30 символов', 'error')
            return render_template('edit_profile.html', user=user)
        
        # Проверяем, не занят ли новый username
        if new_username != user.username:
            existing_user = User.query.filter_by(username=new_username).first()
            if existing_user and existing_user.id != user.id:
                flash('Этот username уже занят', 'error')
                return render_template('edit_profile.html', user=user)
        
        # Обновляем данные профиля
        user.username = new_username
        user.first_name = first_name
        user.last_name = last_name
        user.bio = bio

        # Загрузка аватара (если передан)
        if 'avatar' in request.files:
            avatar_file = request.files['avatar']
            if avatar_file and avatar_file.filename:
                if allowed_file(avatar_file.filename):
                    if not os.path.exists(UPLOAD_FOLDER):
                        os.makedirs(UPLOAD_FOLDER)
                    filename = f"avatar_{session['user_id']}_{int(time.time())}_{secure_filename(avatar_file.filename)}"
                    filepath = os.path.join(UPLOAD_FOLDER, filename)
                    avatar_file.save(filepath)
                    # относительный путь для шаблонов
                    user.avatar = f"uploads/{filename}"
                    session['avatar'] = user.avatar
                else:
                    flash('Неподдерживаемый формат аватара', 'error')
                    return render_template('edit_profile.html', user=user)
        
        # Обновляем сессию
        session['username'] = new_username
        
        # Сохраняем в базу данных
        db.session.commit()
        
        flash('Профиль обновлен!', 'success')
        return redirect(url_for('profile', username=new_username))
    
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

# Получение категорий
@app.route('/api/categories')
def get_categories():
    categories = Category.query.all()
    return jsonify([{
        'id': cat.id,
        'name': cat.name,
        'description': cat.description,
        'color': cat.color,
        'icon': cat.icon
    } for cat in categories])

# Получение популярных тегов
@app.route('/api/tags/popular')
def get_popular_tags():
    tags = Tag.query.order_by(Tag.usage_count.desc()).limit(20).all()
    return jsonify([{
        'id': tag.id,
        'name': tag.name,
        'usage_count': tag.usage_count
    } for tag in tags])

# Проверка доступности username
@app.route('/api/check-username')
def check_username():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    username = request.args.get('username', '').strip()
    if not username:
        return jsonify({'available': False, 'message': 'Username не может быть пустым'})
    
    # Проверяем длину
    if len(username) < 3:
        return jsonify({'available': False, 'message': 'Username должен быть не менее 3 символов'})
    
    if len(username) > 30:
        return jsonify({'available': False, 'message': 'Username должен быть не более 30 символов'})
    
    # Проверяем формат
    import re
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return jsonify({'available': False, 'message': 'Username может содержать только буквы, цифры и подчеркивания'})
    
    # Проверяем, не занят ли username
    existing_user = User.query.filter_by(username=username).first()
    current_user = User.query.get(session['user_id'])
    
    if existing_user and existing_user.id != current_user.id:
        return jsonify({'available': False, 'message': 'Этот username уже занят'})
    
    return jsonify({'available': True, 'message': 'Username доступен'})

# Поиск по тегам
@app.route('/api/tags/search')
def search_tags():
    query = request.args.get('q', '')
    if len(query) < 2:
        return jsonify([])
    
    tags = Tag.query.filter(Tag.name.ilike(f'%{query}%')).limit(10).all()
    return jsonify([{
        'id': tag.id,
        'name': tag.name,
        'usage_count': tag.usage_count
    } for tag in tags])

# Репост поста
@app.route('/repost/<int:post_id>', methods=['POST'])
def repost_post(post_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    original_post = Post.query.get_or_404(post_id)
    
    # Проверяем защиту от накрутки
    if not original_post.can_be_reposted_by(session['user_id']):
        return jsonify({'success': False, 'error': 'Слишком часто репостите'}), 429
    
    # Проверяем, не репостил ли уже пользователь этот пост
    existing_repost = Repost.query.filter_by(
        user_id=session['user_id'],
        original_post_id=post_id
    ).first()
    
    if existing_repost:
        return jsonify({'success': False, 'error': 'Вы уже репостили этот пост'}), 400
    
    # Создаем репост
    repost = Repost(
        user_id=session['user_id'],
        original_post_id=post_id
    )
    
    # Устанавливаем кулдаун для репостов (5 минут)
    original_post.repost_cooldown = datetime.utcnow() + timedelta(minutes=5)
    
    db.session.add(repost)
    db.session.commit()
    
    return jsonify({'success': True})

# Создание истории
@app.route('/create_story', methods=['POST'])
@login_required
def create_story():
    print(f"DEBUG: Попытка создания истории от пользователя {session['user_id']}")
    
    if 'media' not in request.files:
        print("DEBUG: Файл не найден в запросе")
        return jsonify({'success': False, 'error': 'Файл не выбран'})
    
    file = request.files['media']
    caption = request.form.get('caption', '')
    
    print(f"DEBUG: Получен файл: {file.filename}, подпись: {caption}")
    
    if file.filename == '':
        print("DEBUG: Имя файла пустое")
        return jsonify({'success': False, 'error': 'Файл не выбран'})
    
    if file and allowed_file(file.filename):
        # Определяем тип медиа
        media_type = 'video' if file.filename.lower().endswith(('.mp4', '.avi', '.mov', '.wmv')) else 'image'
        
        # Генерируем уникальное имя файла
        filename = secure_filename(f"story_{session['user_id']}_{int(time.time())}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        print(f"DEBUG: Сохраняем файл как {filename}, тип: {media_type}")
        
        try:
            # Сохраняем файл
            file.save(filepath)
            
            # Создаем запись в базе
            story = Story(
                user_id=session['user_id'],
                media_type=media_type,
                media_path=filename,
                caption=caption
            )
            
            db.session.add(story)
            db.session.commit()
            
            print(f"DEBUG: История успешно создана с ID {story.id}")
            return jsonify({'success': True, 'story_id': story.id})
            
        except Exception as e:
            print(f"ERROR при создании истории: {str(e)}")
            return jsonify({'success': False, 'error': f'Ошибка сохранения: {str(e)}'})
    
    print(f"DEBUG: Неподдерживаемый тип файла: {file.filename}")
    return jsonify({'success': False, 'error': 'Неподдерживаемый тип файла'})

# Просмотр истории
@app.route('/view_story/<int:story_id>', methods=['POST'])
@login_required
def view_story(story_id):
    story = Story.query.get_or_404(story_id)
    
    # Проверяем, не просматривал ли уже пользователь эту историю
    existing_view = StoryView.query.filter_by(
        story_id=story_id, 
        user_id=session['user_id']
    ).first()
    
    if not existing_view:
        # Создаем запись о просмотре
        view = StoryView(story_id=story_id, user_id=session['user_id'])
        db.session.add(view)
        
        # Увеличиваем счетчик просмотров
        story.views_count += 1
        
        db.session.commit()
    
    return jsonify({'success': True})

# Получение историй для ленты
@app.route('/api/stories')
@login_required
def get_stories():
    print(f"DEBUG: Получен запрос историй от пользователя {session['user_id']}")
    
    try:
        # Получаем истории за последние 24 часа
        cutoff_time = datetime.utcnow() - timedelta(hours=24)
        
        stories = Story.query.filter(
            Story.created_at >= cutoff_time,
            Story.expires_at > datetime.utcnow()
        ).order_by(Story.created_at.desc()).all()
        
        print(f"DEBUG: Найдено историй: {len(stories)}")
        
        stories_data = []
        for story in stories:
            # Проверяем, просматривал ли текущий пользователь эту историю
            viewed = StoryView.query.filter_by(
                story_id=story.id, 
                user_id=session['user_id']
            ).first() is not None
            
            stories_data.append({
                'id': story.id,
                'user_id': story.user_id,
                'username': story.user.username,
                'first_name': story.user.first_name,
                'last_name': story.user.last_name,
                'media_type': story.media_type,
                'media_path': story.media_path,
                'caption': story.caption,
                'created_at': story.created_at.isoformat(),
                'views_count': story.views_count,
                'viewed': viewed
            })
        
        print(f"DEBUG: Возвращаем {len(stories_data)} историй")
        return jsonify({'stories': stories_data})
        
    except Exception as e:
        print(f"ERROR в get_stories: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Обновление активности пользователя
@app.route('/api/activity', methods=['POST'])
def update_activity():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    user = User.query.get(session['user_id'])
    user.update_last_seen()
    
    # Записываем активность
    activity = UserActivity(
        user_id=session['user_id'],
        activity_type='activity',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent', '')
    )
    
    db.session.add(activity)
    db.session.commit()
    
    return jsonify({'success': True})

# Инициализация базы данных с категориями
def init_categories():
    """Инициализирует базовые категории"""
    categories_data = [
        {'name': 'Общее', 'description': 'Общие посты', 'color': '#3498db', 'icon': 'fas fa-globe'},
        {'name': 'Технологии', 'description': 'Технологии и IT', 'color': '#e74c3c', 'icon': 'fas fa-laptop-code'},
        {'name': 'Развлечения', 'description': 'Развлечения и досуг', 'color': '#f39c12', 'icon': 'fas fa-gamepad'},
        {'name': 'Спорт', 'description': 'Спорт и активность', 'color': '#27ae60', 'icon': 'fas fa-running'},
        {'name': 'Музыка', 'description': 'Музыка и аудио', 'color': '#9b59b6', 'icon': 'fas fa-music'},
        {'name': 'Кино', 'description': 'Фильмы и сериалы', 'color': '#e67e22', 'icon': 'fas fa-film'},
        {'name': 'Кулинария', 'description': 'Рецепты и еда', 'color': '#e74c3c', 'icon': 'fas fa-utensils'},
        {'name': 'Путешествия', 'description': 'Путешествия и туризм', 'color': '#1abc9c', 'icon': 'fas fa-plane'},
        {'name': 'Мода', 'description': 'Мода и стиль', 'color': '#f39c12', 'icon': 'fas fa-tshirt'},
        {'name': 'Авто', 'description': 'Автомобили и транспорт', 'color': '#34495e', 'icon': 'fas fa-car'}
    ]
    
    for cat_data in categories_data:
        existing = Category.query.filter_by(name=cat_data['name']).first()
        if not existing:
            category = Category(**cat_data)
            db.session.add(category)
    
    db.session.commit()

# Инициализация базы данных
def init_db():
    with app.app_context():
        db.create_all()
        init_categories()
        print("База данных инициализирована!")

def migrate_db():
    """Автоматическая миграция базы данных: добавляет недостающие колонки во все таблицы"""
    from sqlalchemy import inspect as sqla_inspect
    from sqlalchemy.schema import CreateTable
    from sqlalchemy.sql import sqltypes
    
    with app.app_context():
        try:
            inspector = sqla_inspect(db.engine)
            existing_tables = set(inspector.get_table_names())
            
            # Функция для преобразования типа SQLAlchemy в SQL тип для SQLite
            def sqlalchemy_to_sqlite_type(col_type):
                """Преобразует тип SQLAlchemy в SQL тип для SQLite"""
                if isinstance(col_type, sqltypes.String):
                    length = getattr(col_type, 'length', None)
                    if length:
                        return f"VARCHAR({length})"
                    return "TEXT"
                elif isinstance(col_type, sqltypes.Text):
                    return "TEXT"
                elif isinstance(col_type, sqltypes.Integer):
                    return "INTEGER"
                elif isinstance(col_type, sqltypes.Boolean):
                    return "INTEGER"  # SQLite использует INTEGER для BOOLEAN
                elif isinstance(col_type, sqltypes.DateTime):
                    return "DATETIME"
                elif isinstance(col_type, sqltypes.Float):
                    return "REAL"
                else:
                    return "TEXT"  # По умолчанию TEXT
            
            # Функция для получения значения по умолчанию
            def get_default_value(column):
                """Получает значение по умолчанию для колонки"""
                if column.default is not None:
                    if hasattr(column.default, 'arg'):
                        default_val = column.default.arg
                        if isinstance(default_val, (str, int, float, bool)):
                            if isinstance(default_val, bool):
                                return 1 if default_val else 0
                            return default_val
                        elif callable(default_val):
                            # Для функций по умолчанию (например, datetime.utcnow)
                            return None
                return None
            
            # Получаем все модели из метаданных
            metadata = db.Model.metadata
            models_added = 0
            columns_added = 0
            
            # Создаем все отсутствующие таблицы
            for table_name, table in metadata.tables.items():
                if table_name not in existing_tables:
                    # Таблица не существует, создаем её
                    db.create_all(tables=[table])
                    print(f"Создана таблица: {table_name}")
                    models_added += 1
                else:
                    # Таблица существует, проверяем колонки
                    existing_columns = {col['name']: col for col in inspector.get_columns(table_name)}
                    
                    for column in table.columns:
                        col_name = column.name
                        
                        # Пропускаем первичные ключи и внешние ключи (они уже должны быть)
                        if column.primary_key:
                            continue
                        
                        if col_name not in existing_columns:
                            # Колонка отсутствует, добавляем её
                            try:
                                sql_type = sqlalchemy_to_sqlite_type(column.type)
                                default_val = get_default_value(column)
                                
                                alter_sql = f'ALTER TABLE {table_name} ADD COLUMN {col_name} {sql_type}'
                                
                                if default_val is not None:
                                    if isinstance(default_val, str):
                                        alter_sql += f" DEFAULT '{default_val}'"
                                    else:
                                        alter_sql += f" DEFAULT {default_val}"
                                
                                with db.engine.connect() as conn:
                                    conn.execute(db.text(alter_sql))
                                    conn.commit()
                                
                                print(f"Добавлено поле '{col_name}' в таблицу '{table_name}'")
                                columns_added += 1
                            except Exception as col_error:
                                print(f"Ошибка при добавлении колонки '{col_name}' в таблицу '{table_name}': {col_error}")
                                # Продолжаем миграцию других колонок
            
            if models_added == 0 and columns_added == 0:
                print("База данных уже актуальна, миграция не требуется.")
            else:
                print(f"Миграция завершена! Создано таблиц: {models_added}, Добавлено колонок: {columns_added}")
                
        except Exception as e:
            print(f"Ошибка при миграции: {e}")
            import traceback
            traceback.print_exc()
            print("Попробуйте пересоздать базу данных")

# ===== МАРШРУТЫ ДЛЯ СООБЩЕСТВ =====

# Список сообществ
@app.route('/communities')
@login_required
def communities():
    # Получаем все публичные сообщества и те, в которых состоит пользователь
    public_communities = Community.query.filter_by(is_private=False).all()
    user_communities = Community.query.join(CommunityMember).filter(
        CommunityMember.user_id == session['user_id']
    ).all()
    
    # Объединяем и убираем дубликаты
    all_communities = list(set(public_communities + user_communities))
    
    # Сортируем по количеству участников
    all_communities.sort(key=lambda c: c.member_count(), reverse=True)
    
    return render_template('communities.html', communities=all_communities, user_id=session['user_id'])

# Создание сообщества
@app.route('/create_community', methods=['POST'])
@login_required
def create_community():
    name = request.form['name']
    description = request.form['description']
    category = request.form['category']
    is_private = request.form.get('is_private', 'false').lower() == 'true'
    
    # Проверяем, не существует ли уже сообщество с таким именем
    existing = Community.query.filter_by(name=name).first()
    if existing:
        return jsonify({'success': False, 'error': 'Сообщество с таким именем уже существует'})
    
    # Обработка аватара
    avatar_path = None
    if 'avatar' in request.files:
        avatar_file = request.files['avatar']
        if avatar_file and avatar_file.filename:
            if allowed_file(avatar_file.filename):
                filename = f"community_avatar_{int(time.time())}_{secure_filename(avatar_file.filename)}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                avatar_file.save(filepath)
                avatar_path = f"uploads/{filename}"
    
    # Обработка обложки
    cover_path = None
    if 'cover_image' in request.files:
        cover_file = request.files['cover_image']
        if cover_file and cover_file.filename:
            if allowed_file(cover_file.filename):
                filename = f"community_cover_{int(time.time())}_{secure_filename(cover_file.filename)}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                cover_file.save(filepath)
                cover_path = f"uploads/{filename}"
    
    # Создаем сообщество
    community = Community(
        name=name,
        description=description,
        category=category,
        is_private=is_private,
        avatar=avatar_path,
        cover_image=cover_path,
        creator_id=session['user_id']
    )
    
    db.session.add(community)
    db.session.commit()
    
    # Добавляем создателя как администратора
    member = CommunityMember(
        user_id=session['user_id'],
        community_id=community.id,
        role='admin'
    )
    db.session.add(member)
    db.session.commit()
    
    return jsonify({
        'success': True, 
        'message': 'Сообщество успешно создано!',
        'community_id': community.id
    })

# Сохранение настроек комментариев
@app.route('/save_comment_settings', methods=['POST'])
@login_required
def save_comment_settings():
    data = request.get_json()
    
    # Получаем ID сообщества (пока используем статичное значение)
    community_id = 1  # В реальном приложении это должно передаваться
    community = Community.query.get(community_id)
    
    if not community:
        return jsonify({'success': False, 'error': 'Сообщество не найдено'})
    
    # Проверяем права администратора
    member = CommunityMember.query.filter_by(
        user_id=session['user_id'], 
        community_id=community_id
    ).first()
    
    if not member or member.role not in ['admin', 'moderator']:
        return jsonify({'success': False, 'error': 'Недостаточно прав для изменения настроек'})
    
    # Обновляем настройки
    community.comments_enabled = data.get('commentsEnabled', True)
    community.profanity_filter = data.get('profanityFilter', False)
    community.hostile_filter = data.get('hostileFilter', False)
    community.keyword_filter = data.get('keywordFilter', False)
    community.banned_keywords = data.get('bannedKeywords', '')
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Настройки комментариев сохранены'
    })

# Страница сообщества
@app.route('/community/<int:community_id>')
@login_required
def community(community_id):
    community = Community.query.get_or_404(community_id)
    
    # Проверяем, является ли пользователь участником
    is_member = CommunityMember.query.filter_by(
        user_id=session['user_id'], 
        community_id=community_id
    ).first()
    
    # Если сообщество приватное и пользователь не участник
    if community.is_private and not is_member:
        flash('Это приватное сообщество. Вы не можете просматривать его содержимое.', 'error')
        return redirect(url_for('communities'))
    
    # Получаем посты сообщества
    posts = CommunityPost.query.filter_by(community_id=community_id).order_by(CommunityPost.created_at.desc()).all()
    
    # Получаем информацию о пользователях для постов
    for post in posts:
        post.user = User.query.get(post.user_id)
        # Проверяем, существует ли пользователь
        if not post.user:
            # Если пользователь не найден, пропускаем пост
            continue
            
        # Получаем комментарии для поста с информацией о пользователях
        comments = CommunityComment.query.filter_by(post_id=post.id).order_by(CommunityComment.created_at.asc()).all()
        for comment in comments:
            comment.user = User.query.get(comment.user_id)
            # Проверяем, существует ли пользователь комментария
            if not comment.user:
                continue
        post._comments_list = comments
        # Подсчитываем количество лайков для поста
        post.likes_count = CommunityLike.query.filter_by(post_id=post.id).count()
        # Проверяем, лайкнул ли текущий пользователь этот пост
        post.user_liked = CommunityLike.query.filter_by(
            user_id=session['user_id'], 
            post_id=post.id
        ).first() is not None
    
    # Фильтруем посты, где пользователь существует
    posts = [post for post in posts if post.user is not None]
    
    # Получаем количество участников
    member_count = community.member_count()
    
    return render_template('community.html', 
                         community=community, 
                         posts=posts, 
                         is_member=is_member,
                         member_count=member_count,
                         user_id=session['user_id'])

# Присоединение к сообществу
@app.route('/join_community/<int:community_id>')
@login_required
def join_community(community_id):
    community = Community.query.get_or_404(community_id)
    
    # Проверяем, не состоит ли уже пользователь в сообществе
    existing_member = CommunityMember.query.filter_by(
        user_id=session['user_id'], 
        community_id=community_id
    ).first()
    
    if existing_member:
        flash('Вы уже состоите в этом сообществе', 'info')
    else:
        # Добавляем пользователя в сообщество
        member = CommunityMember(
            user_id=session['user_id'],
            community_id=community_id,
            role='member'
        )
        db.session.add(member)
        db.session.commit()
        flash(f'Вы успешно присоединились к сообществу "{community.name}"!', 'success')
    
    return redirect(url_for('community', community_id=community_id))

# Выход из сообщества
@app.route('/leave_community/<int:community_id>')
@login_required
def leave_community(community_id):
    community = Community.query.get_or_404(community_id)
    
    # Проверяем, не является ли пользователь создателем
    if community.creator_id == session['user_id']:
        flash('Создатель не может покинуть сообщество. Передайте права другому участнику.', 'error')
        return redirect(url_for('community', community_id=community_id))
    
    # Удаляем пользователя из сообщества
    member = CommunityMember.query.filter_by(
        user_id=session['user_id'], 
        community_id=community_id
    ).first()
    
    if member:
        db.session.delete(member)
        db.session.commit()
        flash(f'Вы покинули сообщество "{community.name}"', 'info')
    
    return redirect(url_for('communities'))

# Создание поста в сообществе
@app.route('/community/<int:community_id>/post', methods=['POST'])
@login_required
def create_community_post(community_id):
    community = Community.query.get_or_404(community_id)
    
    # Разрешаем создавать посты только владельцу сообщества
    if session.get('user_id') != community.creator_id:
        flash('Только владелец может публиковать посты от имени сообщества', 'error')
        return redirect(url_for('community', community_id=community_id))
    
    content = request.form['content']
    if content.strip():
        # Получаем медиа данные из формы
        emoji = request.form.get('emoji', '')
        location = request.form.get('location', '')
        location_name = request.form.get('location_name', '')
        visibility = request.form.get('visibility', 'public')
        category = request.form.get('category', '')
        tags = request.form.get('tags', '')
        
        # Обработка изображения
        image_path = None
        if 'image' in request.files:
            image_file = request.files['image']
            if image_file and image_file.filename:
                if allowed_file(image_file.filename):
                    filename = f"community_post_{session['user_id']}_{int(time.time())}_{secure_filename(image_file.filename)}"
                    image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    image_file.save(image_path)
                    image_path = f"uploads/{filename}"
        
        # Обработка видео
        video_path = None
        if 'video' in request.files:
            video_file = request.files['video']
            if video_file and video_file.filename:
                if allowed_file(video_file.filename):
                    filename = f"community_post_{session['user_id']}_{int(time.time())}_{secure_filename(video_file.filename)}"
                    video_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    video_file.save(video_path)
                    video_path = f"uploads/{filename}"
        
        # Создаем пост
        post = CommunityPost(
            content=content,
            image=image_path,
            video=video_path,
            emoji=emoji,
            location=location,
            location_name=location_name,
            visibility=visibility,
            category=category,
            tags=tags,
            user_id=session['user_id'],
            community_id=community_id
        )
        
        db.session.add(post)
        db.session.commit()
        
        flash('Пост опубликован в сообществе!', 'success')
    
    return redirect(url_for('community', community_id=community_id))

# Лайк поста сообщества
@app.route('/like_community_post/<int:post_id>', methods=['POST'])
@login_required
def like_community_post(post_id):
    post = CommunityPost.query.get_or_404(post_id)
    
    # Проверяем, является ли пользователь участником сообщества
    is_member = CommunityMember.query.filter_by(
        user_id=session['user_id'], 
        community_id=post.community_id
    ).first()
    
    if not is_member:
        return jsonify({'success': False, 'error': 'Вы должны быть участником сообщества'})
    
    # Проверяем, есть ли уже лайк
    existing_like = CommunityLike.query.filter_by(
        user_id=session['user_id'], 
        post_id=post_id
    ).first()
    
    if existing_like:
        # Убираем лайк
        db.session.delete(existing_like)
        liked = False
    else:
        # Добавляем лайк
        new_like = CommunityLike(
            user_id=session['user_id'], 
            post_id=post_id
        )
        db.session.add(new_like)
        liked = True
    
    db.session.commit()
    
    # Подсчитываем количество лайков
    likes_count = CommunityLike.query.filter_by(post_id=post_id).count()
    
    return jsonify({
        'success': True, 
        'liked': liked, 
        'likes_count': likes_count
    })

# Добавление комментария к посту сообщества
@app.route('/add_community_comment/<int:post_id>', methods=['POST'])
@login_required
def add_community_comment(post_id):
    post = CommunityPost.query.get_or_404(post_id)
    
    # Проверяем, является ли пользователь участником сообщества
    is_member = CommunityMember.query.filter_by(
        user_id=session['user_id'], 
        community_id=post.community_id
    ).first()
    
    if not is_member:
        return jsonify({'success': False, 'error': 'Вы должны быть участником сообщества'})
    
    data = request.get_json()
    content = data.get('content', '').strip()
    
    if not content:
        return jsonify({'success': False, 'error': 'Комментарий не может быть пустым'})
    
    # Получаем сообщество для применения фильтров
    community = Community.query.get(post.community_id)
    
    # Применяем фильтры комментариев
    is_allowed, message = apply_comment_filters(content, community)
    if not is_allowed:
        return jsonify({'success': False, 'error': message})
    
    # Создаем комментарий
    comment = CommunityComment(
        content=content,
        user_id=session['user_id'],
        post_id=post_id
    )
    
    db.session.add(comment)
    db.session.commit()
    
    return jsonify({'success': True})

def get_weekly_activity(community_id):
    """Получает данные активности сообщества за последние 7 дней"""
    from datetime import datetime, timedelta
    
    # Получаем дату 7 дней назад
    week_ago = datetime.now() - timedelta(days=7)
    
    # Получаем посты за неделю
    weekly_posts = CommunityPost.query.filter(
        CommunityPost.community_id == community_id,
        CommunityPost.created_at >= week_ago
    ).all()
    
    # Получаем комментарии за неделю
    weekly_comments = CommunityComment.query.join(CommunityPost).filter(
        CommunityPost.community_id == community_id,
        CommunityComment.created_at >= week_ago
    ).all()
    
    # Получаем лайки за неделю
    weekly_likes = CommunityLike.query.join(CommunityPost).filter(
        CommunityPost.community_id == community_id,
        CommunityLike.created_at >= week_ago
    ).all()
    
    # Отладочная информация
    print(f"DEBUG: week_ago = {week_ago}")
    print(f"DEBUG: Found {len(weekly_posts)} posts")
    print(f"DEBUG: Found {len(weekly_comments)} comments")
    print(f"DEBUG: Found {len(weekly_likes)} likes")
    
    for post in weekly_posts:
        print(f"DEBUG: Post {post.id} created at {post.created_at} (weekday: {post.created_at.weekday()})")
    
    for comment in weekly_comments:
        print(f"DEBUG: Comment {comment.id} created at {comment.created_at} (weekday: {comment.created_at.weekday()})")
    
    for like in weekly_likes:
        print(f"DEBUG: Like {like.id} created at {like.created_at} (weekday: {like.created_at.weekday()})")
    
    # Группируем по дням недели
    activity_data = {
        'Понедельник': {'posts': 0, 'comments': 0, 'likes': 0},
        'Вторник': {'posts': 0, 'comments': 0, 'likes': 0},
        'Среда': {'posts': 0, 'comments': 0, 'likes': 0},
        'Четверг': {'posts': 0, 'comments': 0, 'likes': 0},
        'Пятница': {'posts': 0, 'comments': 0, 'likes': 0},
        'Суббота': {'posts': 0, 'comments': 0, 'likes': 0},
        'Воскресенье': {'posts': 0, 'comments': 0, 'likes': 0}
    }
    
    # Заполняем данные по дням
    for post in weekly_posts:
        # Получаем номер дня недели (0 = понедельник, 6 = воскресенье)
        day_of_week = post.created_at.weekday()
        if day_of_week == 0:
            activity_data['Понедельник']['posts'] += 1
        elif day_of_week == 1:
            activity_data['Вторник']['posts'] += 1
        elif day_of_week == 2:
            activity_data['Среда']['posts'] += 1
        elif day_of_week == 3:
            activity_data['Четверг']['posts'] += 1
        elif day_of_week == 4:
            activity_data['Пятница']['posts'] += 1
        elif day_of_week == 5:
            activity_data['Суббота']['posts'] += 1
        elif day_of_week == 6:
            activity_data['Воскресенье']['posts'] += 1
    
    for comment in weekly_comments:
        day_of_week = comment.created_at.weekday()
        if day_of_week == 0:
            activity_data['Понедельник']['comments'] += 1
        elif day_of_week == 1:
            activity_data['Вторник']['comments'] += 1
        elif day_of_week == 2:
            activity_data['Среда']['comments'] += 1
        elif day_of_week == 3:
            activity_data['Четверг']['comments'] += 1
        elif day_of_week == 4:
            activity_data['Пятница']['comments'] += 1
        elif day_of_week == 5:
            activity_data['Суббота']['comments'] += 1
        elif day_of_week == 6:
            activity_data['Воскресенье']['comments'] += 1
    
    for like in weekly_likes:
        day_of_week = like.created_at.weekday()
        if day_of_week == 0:
            activity_data['Понедельник']['likes'] += 1
        elif day_of_week == 1:
            activity_data['Вторник']['likes'] += 1
        elif day_of_week == 2:
            activity_data['Среда']['likes'] += 1
        elif day_of_week == 3:
            activity_data['Четверг']['likes'] += 1
        elif day_of_week == 4:
            activity_data['Пятница']['likes'] += 1
        elif day_of_week == 5:
            activity_data['Суббота']['likes'] += 1
        elif day_of_week == 6:
            activity_data['Воскресенье']['likes'] += 1
    
    return activity_data

# Редактирование сообщества
@app.route('/edit_community/<int:community_id>', methods=['GET', 'POST'])
@login_required
def edit_community(community_id):
    community = Community.query.get_or_404(community_id)
    
    # Проверяем, является ли пользователь создателем сообщества
    if community.creator_id != session['user_id']:
        flash('Только создатель может редактировать сообщество', 'error')
        return redirect(url_for('community', community_id=community_id))
    
    if request.method == 'POST':
        # Проверяем, какая форма была отправлена
        if 'name' in request.form:
            # Форма основной информации
            name = request.form.get('name', '')
            description = request.form.get('description', '')
            
            # Проверяем, что название не пустое
            if not name.strip():
                flash('Название сообщества не может быть пустым', 'error')
                return redirect(url_for('edit_community', community_id=community_id))
            
            # Проверяем, не существует ли уже сообщество с таким именем (кроме текущего)
            existing = Community.query.filter(
                Community.name == name,
                Community.id != community_id
            ).first()
            if existing:
                flash('Сообщество с таким именем уже существует', 'error')
                return redirect(url_for('edit_community', community_id=community_id))
            
            # Обновляем аватар, если загружен новый
            if 'avatar' in request.files:
                avatar_file = request.files['avatar']
                if avatar_file and avatar_file.filename:
                    if allowed_file(avatar_file.filename):
                        filename = f"community_avatar_{int(time.time())}_{secure_filename(avatar_file.filename)}"
                        avatar_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                        avatar_file.save(avatar_path)
                        community.avatar = os.path.join('uploads', filename)
            
            # Обновляем основную информацию
            community.name = name
            community.description = description
            community.is_private = request.form.get('is_private') == 'true'
            
            flash('Основная информация успешно обновлена!', 'success')
            
        else:
            # Форма дополнительных настроек
            category = request.form.get('category', '')
            website = request.form.get('website', '')
            phone = request.form.get('phone', '')
            city = request.form.get('city', '')
            
            # Обновляем дополнительные настройки
            community.category = category
            community.website = website
            community.phone = phone
            community.city = city
            
            flash('Дополнительные настройки успешно обновлены!', 'success')
        
        db.session.commit()
        return redirect(url_for('edit_community', community_id=community_id))

    # GET запрос - показываем форму редактирования
    # Получаем статистику сообщества
    member_count = community.member_count()
    post_count = community.post_count()
    
    # Получаем участников сообщества
    members = CommunityMember.query.filter_by(community_id=community_id).all()
    
    # Подсчитываем общее количество комментариев
    comment_count = 0
    for post in community.posts:
        comment_count += post.comments.count()
    
    # Подсчитываем общее количество лайков
    like_count = 0
    for post in community.posts:
        # Используем модель CommunityLike для точного подсчета
        post_likes = CommunityLike.query.filter_by(post_id=post.id).count()
        like_count += post_likes
    
    # Получаем данные активности за неделю
    weekly_activity = get_weekly_activity(community_id)
    
    return render_template('edit_community.html', 
                         community=community,
                         member_count=member_count,
                         post_count=post_count,
                         comment_count=comment_count,
                         like_count=like_count,
                         members=members,
                         weekly_activity=weekly_activity,
                         session=session)

# Удаление поста сообщества
@app.route('/delete_community_post/<int:post_id>', methods=['POST'])
@login_required
def delete_community_post(post_id):
    post = CommunityPost.query.get_or_404(post_id)
    
    # Проверяем, является ли пользователь автором поста или создателем сообщества
    community = Community.query.get(post.community_id)
    if post.user_id != session['user_id'] and community.creator_id != session['user_id']:
        return jsonify({'success': False, 'error': 'У вас нет прав для удаления этого поста'})
    
    # Удаляем все лайки и комментарии поста
    CommunityLike.query.filter_by(post_id=post_id).delete()
    CommunityComment.query.filter_by(post_id=post_id).delete()
    
    # Удаляем сам пост
    db.session.delete(post)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Пост успешно удален'})

# Удаление комментария к посту сообщества
@app.route('/delete_community_comment/<int:comment_id>', methods=['POST'])
@login_required
def delete_community_comment(comment_id):
    comment = CommunityComment.query.get_or_404(comment_id)
    
    # Проверяем, является ли пользователь автором комментария или создателем сообщества
    post = CommunityPost.query.get(comment.post_id)
    if not post:
        return jsonify({'success': False, 'error': 'Пост не найден'})
    
    community = Community.query.get(post.community_id)
    if comment.user_id != session['user_id'] and community.creator_id != session['user_id']:
        return jsonify({'success': False, 'error': 'У вас нет прав для удаления этого комментария'})
    
    # Удаляем комментарий
    db.session.delete(comment)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Комментарий успешно удален'})

# ===== УПРАВЛЕНИЕ УЧАСТНИКАМИ СООБЩЕСТВА =====

# Добавление участника в сообщество
@app.route('/add_community_member/<int:community_id>', methods=['POST'])
@login_required
def add_community_member(community_id):
    community = Community.query.get_or_404(community_id)
    
    # Проверяем, является ли пользователь создателем сообщества
    if community.creator_id != session['user_id']:
        return jsonify({'success': False, 'error': 'Только создатель может добавлять участников'})
    
    username = request.form.get('username', '').strip()
    if not username:
        return jsonify({'success': False, 'error': 'Введите имя пользователя'})
    
    # Ищем пользователя
    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({'success': False, 'error': 'Пользователь не найден'})
    
    # Проверяем, не состоит ли уже пользователь в сообществе
    existing_member = CommunityMember.query.filter_by(
        user_id=user.id, 
        community_id=community_id
    ).first()
    
    if existing_member:
        return jsonify({'success': False, 'error': 'Пользователь уже состоит в сообществе'})
    
    # Добавляем пользователя в сообщество
    member = CommunityMember(
        user_id=user.id,
        community_id=community_id,
        role='member'
    )
    
    db.session.add(member)
    db.session.commit()
    
    return jsonify({
        'success': True, 
        'message': f'Пользователь {username} успешно добавлен в сообщество',
        'member': {
            'id': user.id,
            'username': user.username,
            'role': 'member'
        }
    })

# Удаление участника из сообщества
@app.route('/remove_community_member/<int:community_id>/<int:user_id>', methods=['POST'])
@login_required
def remove_community_member(community_id, user_id):
    community = Community.query.get_or_404(community_id)
    
    # Проверяем, является ли пользователь создателем сообщества
    if community.creator_id != session['user_id']:
        return jsonify({'success': False, 'error': 'Только создатель может удалять участников'})
    
    # Проверяем, не пытается ли создатель удалить сам себя
    if user_id == session['user_id']:
        return jsonify({'success': False, 'error': 'Создатель не может удалить себя из сообщества'})
    
    # Ищем участника
    member = CommunityMember.query.filter_by(
        user_id=user_id, 
        community_id=community_id
    ).first()
    
    if not member:
        return jsonify({'success': False, 'error': 'Участник не найден'})
    
    # Удаляем участника
    db.session.delete(member)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Участник успешно удален из сообщества'})

# Изменение роли участника
@app.route('/change_member_role/<int:community_id>/<int:user_id>', methods=['POST'])
@login_required
def change_member_role(community_id, user_id):
    community = Community.query.get_or_404(community_id)
    
    # Проверяем, является ли пользователь создателем сообщества
    if community.creator_id != session['user_id']:
        return jsonify({'success': False, 'error': 'Только создатель может изменять роли участников'})
    
    new_role = request.form.get('role', '').strip()
    if new_role not in ['member', 'moderator', 'admin']:
        return jsonify({'success': False, 'error': 'Неверная роль'})
    
    # Ищем участника
    member = CommunityMember.query.filter_by(
        user_id=user_id, 
        community_id=community_id
    ).first()
    
    if not member:
        return jsonify({'success': False, 'error': 'Участник не найден'})
    
    # Изменяем роль
    member.role = new_role
    db.session.commit()
    
    return jsonify({
        'success': True, 
        'message': f'Роль участника изменена на {new_role}'
    })

if __name__ == '__main__':
    init_db()
    migrate_db()  # Запускаем миграцию для добавления новых полей
    app.run(debug=True)
