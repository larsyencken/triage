import re

try:
    from hashlib import md5
except:
    from md5 import new as md5

from time import time
from mongoengine import *
from mongoengine.queryset import DoesNotExist, QuerySet
from passlib.apps import custom_app_context as pwd_context


class ErrorHasher:
    digit_re = re.compile('\d+')
    string_re = re.compile(r'".*?(?<!\\)"|\'.*?(?<!\\)\'')

    def __init__(self, error):
        self.error = error

    def get_hash(self):
        return md5(str(self.get_identity())).hexdigest()

    def get_identity(self):
        return {
            'project': self.error['project'],
            'language': self.error['language'],
            'type': self.error['type'],
            'message': self.digit_re.sub('', self.string_re.sub('', self.error['message']))
        }


class Project(Document):
    name = StringField(required=True)


class User(Document):
    name = StringField(required=True)
    email = EmailField(required=True)
    password = StringField(required=True)
    created = IntField(required=True)
    tzoffset = IntField()

    @classmethod
    def from_data(cls, data):
        return cls(
                name=data['name'],
                email=data['email'],
                password=pwd_context.encrypt(data['password']),
                created=int(time())
            )

    def update(user, data):
        for field in ['name', 'email', 'tzoffset']:
            user[field] = data[field]

        if data['password']:
            user.password = pwd_context.encrypt(data['password'])

        return user


class Tag(Document):
    meta = {
        'ordering': ['-count']
    }

    tag = StringField(required=True)
    count = IntField(required=True)
    created = IntField(required=True)

    @classmethod
    def create(cls, value):
        try:
            tag = cls.objects.get(tag=value)
            tag.count = tag.count + 1
        except DoesNotExist:
            tag = cls.create_from_tag(value)
        return tag

    @classmethod
    def removeOne(cls, value):
        try:
            tag = cls.objects.get(tag=value)
            tag.count = tag.count - 1
            tag.save()
        except DoesNotExist:
            pass

    @classmethod
    def create_from_tag(cls, value):
        tag = cls()
        tag.tag = value
        tag.count = 1
        tag.created = int(time())
        return tag


class Comment(EmbeddedDocument):
    author = ReferenceField(User, required=True)
    content = StringField(required=True)
    created = IntField(required=True)


class ErrorInstance(Document):
    meta = {
        'allow_inheritance': False,
        'ordering': ['-timestamp'],
        'indexes': ['hash', 'timestamp', ('hash', '-timestamp')]
    }

    hash = StringField(required=True)
    project = StringField(required=True)
    language = StringField(required=True)
    message = StringField(required=True)
    type = StringField(required=True)
    line = IntField()
    file = StringField()
    context = DictField()
    backtrace = ListField(DictField())
    timestamp = FloatField()

    @classmethod
    def from_raw(cls, raw):
        return cls(**raw)


class ErrorQuerySet(QuerySet):

    def search(self, search_keywords):
        search_keywords = re.split("\s+", search_keywords)

        qObjects = Q()
        for keyword in search_keywords:
            qObjects = qObjects | Q(keywords__icontains=keyword) | Q(type__icontains=keyword) | Q(tags__icontains=keyword)

        return self.filter(qObjects)

    def resolved(self, project):
        selected_project = project['id']
        self.filter(project=selected_project)
        return self.filter( hiddenby__exists=True)

    def active(self, project):
        selected_project = project['id']
        self.filter(project=selected_project)
        return self.filter( hiddenby__exists=False)

keyword_re = re.compile(r'\w+')
class Error(Document):
    meta = {
        'queryset_class': ErrorQuerySet,
        'allow_inheritance': False,
        'ordering': ['-timelatest'],
        'indexes': ['count', 'timelatest', 'comments', 'hash', 'keywords']
    }

    hash = StringField(required=True, unique=True)
    project = StringField(required=True)
    language = StringField(required=True)
    message = StringField(required=True)
    type = StringField(required=True)
    line = IntField()
    file = StringField()
    context = DictField()
    backtrace = ListField(DictField())
    timelatest = FloatField()
    timefirst = FloatField()
    count = IntField()
    claimedby = ReferenceField(User)
    keywords = ListField(StringField())
    tags = ListField(StringField(max_length=30))
    comments = ListField(EmbeddedDocumentField(Comment))
    seenby = ListField(ReferenceField(User))
    hiddenby = ReferenceField(User)

    @classmethod
    def validate_and_upsert(cls, msg):
        msg['timelatest'] = msg['timestamp']

        error = cls.create_from_msg(msg)
        error.validate()

        keywords = list(set(keyword_re.findall(msg['message'].lower())))

        insert_doc = {
                'hash': msg['hash'],
                'project': msg['project'],
                'language': msg['language'],
                'message': msg['message'],
                'type': msg['type'],
                'line': msg['line'],
                'file': msg['file'],
                'context': msg['context'],
                'backtrace': msg['backtrace'],
                'timelatest': msg['timelatest'],
                'timefirst': msg['timelatest'],
                'keywords': keywords,
                'count': 1
        }

        update_doc = {
            '$set': {
                'hash': msg['hash'],
                'project': msg['project'],
                'language': msg['language'],
                'message': msg['message'],
                'type': msg['type'],
                'line': msg['line'],
                'file': msg['file'],
                'context': msg['context'],
                'backtrace': msg['backtrace'],
                'timelatest': msg['timelatest'],
            },
            '$unset': {
                'hiddenby': 1
            },
            '$inc': {
                'count': 1
            },
            '$addToSet': { 
                'keywords': {
                    '$each' : keywords 
                } 
            }
        }

        collection = cls.objects._collection #probs a hack

        # Update fails if document not found
        collection.update({'hash':msg['hash']}, update_doc)
        # insert fails if unique index violated
        collection.insert(insert_doc)

    @classmethod
    def from_msg(cls, msg):
        hash = ErrorHasher(msg).get_hash()
        msg['hash'] = hash
        try:
            error = cls.objects.get(hash=hash)
            error.update_from_msg(msg)
        except DoesNotExist:
            error = cls.create_from_msg(msg)
        return error

    @classmethod
    def create_from_msg(cls, msg):
        now = int(time())
        error = cls(**msg)
        error.count = 0
        error.update_from_msg(msg)
        return error

    def update_from_msg(self, msg):
        self.message = msg['message']
        self.timelatest = msg['timestamp']
        self.count = self.count + 1
        self.hiddenby = None

    def get_row_classes(self, user):
        classes = []
        user not in self.seenby and classes.append('unseen')
        user in self.seenby and classes.append('seen')
        self.hiddenby and classes.append('hidden')
        self.claimedby == user and classes.append('mine')
        return ' '.join(classes)
