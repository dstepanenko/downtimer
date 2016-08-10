import sqlalchemy as sa
from sqlalchemy import orm

Base = declarative_base()


class HasId(object):
    """id mixin, add to subclasses that have an id."""
    id = sa.Column(sa.String(36),
                   primary_key=True,
                   default=uuidutils.generate_uuid)

class Service(Base, HasId):
    __tablename__ = 'services'

    name = sa.Column(sa.String(255))
    address = sa.Column(sa.String(255))
    status_code = sa.Column(sa.Integer)
    timeout = sa.Column(sa.Float)
    elapsed_time = sa.Column(sa.Float)


class Instance(Base, HasId):
    __tablename__ = 'instances'

    address = sa.Column(sa.String(255))
    total_time = sa.Column(sa.Float)
    exit_code = sa.Column(sa.Integer)
    packet_loss = = sa.Column(sa.Float)
