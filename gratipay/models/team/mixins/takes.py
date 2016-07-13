from __future__ import absolute_import, division, print_function, unicode_literals

from collections import OrderedDict
from decimal import Decimal as D


ZERO = D('0.00')
PENNY = D('0.01')


class TakesMixin(object):
    """:py:class:`~gratipay.models.participant.Participant` s who are members
    of a :py:class:`~gratipay.models.team.Team` may take money from the team
    during :py:class:`~gratipay.billing.payday.Payday`. Only the team owner may
    add a new member, by setting their take to a penny, but team owners may
    *only* set their take to a penny---no more. Team owners may also remove
    members, by setting their take to zero, as may the members themselves, who
    may also set their take to whatever they wish.
    """

    #: The total amount of money the team distributes to participants
    #: (including the owner) during payday. Read-only; equal to
    #: :py:attr:`~gratipay.models.team.Team.receiving`.

    distributing = 0


    #: The number of participants (including the owner) that the team
    #: distributes money to during payday. Read-only; modified by
    #: :py:meth:`set_take_for`.

    ndistributing_to = 0


    def get_take_last_week_for(self, member):
        """Get the user's nominal take last week.
        """
        membername = member.username if hasattr(member, 'username') \
                                                        else member['username']
        return self.db.one("""

            SELECT amount
              FROM takes
             WHERE team=%s AND member=%s
               AND mtime < (
                       SELECT ts_start
                         FROM paydays
                        WHERE ts_end > ts_start
                     ORDER BY ts_start DESC LIMIT 1
                   )
          ORDER BY mtime DESC LIMIT 1

        """, (self.username, membername), default=ZERO)


    def set_take_for(self, participant, take, recorder, cursor=None):
        """Set the amount a participant wants to take from this team during payday.

        :param Participant participant: the participant to set the take for
        :param int take: the amount the participant wants to take
        :param Participant recorder: the participant making the change

        :return: ``None``
        :raises: :py:exc:`NotAllowed`

        It is a bug to pass in a ``participant`` or ``recorder`` that is
        suspicious, unclaimed, or without a verified email and identity.
        Furthermore, :py:exc:`NotAllowed` is raised in the following circumstances:

        - ``recorder`` is neither ``participant`` nor the team owner
        - ``recorder`` is the team owner and ``take`` is neither zero nor $0.01
        - ``recorder`` is ``participant``, but ``participant`` isn't already on the team

        """
        def vet(p):
            assert not p.is_suspicious, p.id
            assert p.is_claimed, p.id
            assert p.email_address, p.id
            assert p.has_verified_identity, p.id

        vet(participant)
        vet(recorder)

        if recorder.username == self.owner:
            if take not in (ZERO, PENNY):
                raise NotAllowed('owner can only add and remove members, not otherwise set takes')
        elif recorder != participant:
            raise NotAllowed('can only set own take')

        with self.db.get_cursor(cursor) as cursor:
            cursor.run("LOCK TABLE takes IN EXCLUSIVE MODE")  # avoid race conditions

            # Compute the current takes
            old_takes = self.compute_actual_takes(cursor)

            old_take = self.get_take_for(participant, cursor=cursor)
            if recorder.username != self.owner:
                if recorder == participant and not old_take:
                    raise NotAllowed('can only set take if already a member of the team')

            cursor.one( """

                INSERT INTO takes
                            (ctime, participant_id, team_id, amount, recorder_id)
                     VALUES ( COALESCE (( SELECT ctime
                                            FROM takes
                                           WHERE (participant_id=%(participant_id)s
                                                  AND team_id=%(team_id)s)
                                           LIMIT 1
                                         ), CURRENT_TIMESTAMP)
                            , %(participant_id)s, %(team_id)s, %(amount)s, %(recorder_id)s
                             )
                  RETURNING *

            """, { 'participant_id': participant.id
                 , 'team_id': self.id
                 , 'amount': take
                 , 'recorder_id': recorder.id
                  })

            # Compute the new takes
            new_takes = self.compute_actual_takes(cursor)

            # Update computed values
            self.update_taking(old_takes, new_takes, cursor, participant)
            self.update_distributing(old_takes, new_takes, cursor, participant)


    def get_take_for(self, participant, cursor=None):
        """
        :param Participant participant: the participant to get the take for
        :param GratipayDB cursor: a database cursor; if ``None``, a new cursor will be used
        :return: a :py:class:`~decimal.Decimal`: the ``participant``'s take from this team, or 0.
        """
        return (cursor or self.db).one("""

            SELECT amount
              FROM current_takes
             WHERE team_id=%s AND participant_id=%s

        """, (self.id, participant.id), default=ZERO)


    def update_taking(self, old_takes, new_takes, cursor=None, member=None):
        """Update `taking` amounts based on the difference between `old_takes`
        and `new_takes`.
        """
        # XXX Deal with owner as well as members
        for username in set(old_takes.keys()).union(new_takes.keys()):
            if username == self.username:
                continue
            old = old_takes.get(username, {}).get('actual_amount', ZERO)
            new = new_takes.get(username, {}).get('actual_amount', ZERO)
            diff = new - old
            if diff != 0:
                r = (cursor or self.db).one("""
                    UPDATE participants
                       SET taking = (taking + %(diff)s)
                         , receiving = (receiving + %(diff)s)
                     WHERE username=%(username)s
                 RETURNING taking, receiving
                """, dict(username=username, diff=diff))
                if member and username == member.username:
                    member.set_attributes(**r._asdict())


    def get_current_takes(self, cursor=None):
        """Return a list of member takes for a team.
        """
        TAKES = """
            SELECT member, amount, ctime, mtime
              FROM current_takes
             WHERE team=%(team)s
          ORDER BY ctime DESC
        """
        records = (cursor or self.db).all(TAKES, dict(team=self.username))
        return [r._asdict() for r in records]


    def compute_actual_takes(self, cursor=None):
        """Get the takes, compute the actual amounts, and return an OrderedDict.
        """
        actual_takes = OrderedDict()
        nominal_takes = self.get_current_takes(cursor=cursor)
        budget = balance = self.balance + self.receiving - self.giving
        for take in nominal_takes:
            nominal_amount = take['nominal_amount'] = take.pop('amount')
            actual_amount = take['actual_amount'] = min(nominal_amount, balance)
            if take['member'] != self.username:
                balance -= actual_amount
            take['balance'] = balance
            take['percentage'] = (actual_amount / budget) if budget > 0 else 0
            actual_takes[take['member']] = take
        return actual_takes


class NotAllowed(Exception):
    """Raised by :py:meth:`set_take_for` if ``recorder`` is not allowed to set
    the take for ``participant``.
    """
