"""
Serviços da Room List — Fase 2.1 (Implementação Definitiva com Errata Gate 1D)

Convenções:
- Toda operação de escrita usa @transaction.atomic e select_for_update().
- Instâncias recebidas por parâmetro são reconsultadas pelo ORM dentro da transação.
- Ordem global de aquisição de locks: Show → RoomList → Room (pk↑) → RoomListParticipant (pk↑).
- content_revision é lida e incrementada sob lock somente mediante mutação real de conteúdo.
"""

from dataclasses import dataclass, field
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import (
    Band,
    Integrante,
    LodgingTemplate,
    Room,
    RoomList,
    RoomListParticipant,
    Show,
    ShowParticipant,
    TemplateParticipant,
    TemplateRoom,
    User,
)


# ============================================================
# HIERARQUIA DE EXCEÇÕES
# ============================================================

class RoomListServiceError(Exception):
    """Erro base dos serviços de Room List."""


class RoomListNotFoundError(RoomListServiceError):
    """Room List não encontrada ou não pertence à banda."""


class RoomListNotEditableError(RoomListServiceError):
    """Status não permite edição (PUBLICADA ou ARQUIVADA)."""


class RoomListArchivedError(RoomListNotEditableError):
    """Room List está arquivada."""


class RoomListPublishedError(RoomListNotEditableError):
    """Room List está publicada e precisa ser reaberta para edição."""


class DuplicateRoomNumberError(RoomListServiceError):
    """Já existe um quarto com este número ou nome nesta Room List."""


class DuplicateParticipantError(RoomListServiceError):
    """Integrante já está registrado nesta Room List."""


class RoomOverCapacityError(RoomListServiceError):
    """O quarto já atingiu sua capacidade máxima."""


class RoomCapacityTypeMismatchError(RoomListServiceError):
    """A capacidade informada é incompatível com o tipo de quarto."""


class BandAccessDeniedError(RoomListServiceError):
    """Usuário não tem acesso à banda ou não é produtor."""


class ActiveRoomListExistsError(RoomListServiceError):
    """Já existe uma Room List ativa (RASCUNHO ou PUBLICADA) para este show."""


class PublicationBlockedError(RoomListServiceError):
    """Existem pendências bloqueantes que impedem a publicação."""

    def __init__(self, message, pending_issues):
        super().__init__(message)
        self.pending_issues = pending_issues


# ============================================================
# DATA CLASSES DE RELATÓRIO
# ============================================================

@dataclass
class PendingIssue:
    category: str
    severity: str           # 'blocking' ou 'warning'
    description: str
    related_object_id: int
    related_object_type: str


@dataclass
class PendingIssuesReport:
    issues: list = field(default_factory=list)

    @property
    def has_blocking(self) -> bool:
        return any(i.severity == 'blocking' for i in self.issues)

    @property
    def blocking_issues(self) -> list:
        return [i for i in self.issues if i.severity == 'blocking']

    @property
    def warning_issues(self) -> list:
        return [i for i in self.issues if i.severity == 'warning']


# ============================================================
# CAPACIDADE EXATA POR TIPO
# ============================================================

_CAPACITY_LIMITS = {
    Room.RoomTypeChoices.INDIVIDUAL: 1,
    Room.RoomTypeChoices.CASAL: 2,
    Room.RoomTypeChoices.DUPLO: 2,
    Room.RoomTypeChoices.TRIPLO: 3,
    Room.RoomTypeChoices.QUADRUPLO: 4,
    # PERSONALIZADO não possui limite pré-definido
}


# ============================================================
# VALIDAÇÕES
# ============================================================

def validate_band_access(user, band):
    """
    Verifica que o usuário pertence à banda e tem perfil de produtor.

    Raises:
        BandAccessDeniedError: Se o usuário não pertence à banda ou não é produtor.
    """
    if not user or not user.is_active:
        raise BandAccessDeniedError("Usuário inativo ou não informado.")
    if user.band_id != band.id:
        raise BandAccessDeniedError("Usuário não pertence a esta banda.")
    if not user.is_produtor():
        raise BandAccessDeniedError("Apenas produtores podem executar esta operação.")


def validate_room_capacity_for_type(room_type, capacity):
    """
    Verifica que a capacidade respeita o valor exato do tipo de quarto.

    Raises:
        RoomCapacityTypeMismatchError: Se a capacidade difere do valor exato do tipo ou tipo for desconhecido.
    """
    if type(capacity) is not int or capacity <= 0 or isinstance(capacity, bool):
        raise RoomCapacityTypeMismatchError("A capacidade deve ser um número inteiro positivo real.")

    if room_type not in Room.RoomTypeChoices.values:
        raise RoomCapacityTypeMismatchError(f"Tipo de quarto desconhecido: {room_type}")

    if room_type == Room.RoomTypeChoices.PERSONALIZADO:
        return

    expected_cap = _CAPACITY_LIMITS.get(room_type)
    if expected_cap is not None:
        if room_type == Room.RoomTypeChoices.CASAL:
            if capacity not in [1, 2]:
                raise RoomCapacityTypeMismatchError(
                    f"O tipo '{room_type}' exige capacidade de 1 ou 2 ocupante(s), "
                    f"mas foi informado {capacity}."
                )
        elif capacity != expected_cap:
            raise RoomCapacityTypeMismatchError(
                f"O tipo '{room_type}' exige capacidade exata de {expected_cap} ocupante(s), "
                f"mas foi informado {capacity}."
            )


def _assert_room_list_editable(room_list):
    """
    Verifica que a Room List está em RASCUNHO (único status que permite edição).

    Raises:
        RoomListArchivedError: Se está ARQUIVADA.
        RoomListPublishedError: Se está PUBLICADA.
    """
    if room_list.status == RoomList.StatusChoices.ARQUIVADA:
        raise RoomListArchivedError("Não é possível editar uma Room List arquivada.")
    if room_list.status == RoomList.StatusChoices.PUBLICADA:
        raise RoomListPublishedError(
            "Não é possível editar uma Room List publicada. "
            "Reabra-a antes de fazer alterações."
        )


# ============================================================
# CONSULTAS E PENDÊNCIAS
# ============================================================

def get_room_list_for_band(room_list_id, band):
    """
    Obtém Room List verificando que pertence à banda.

    Returns:
        RoomList

    Raises:
        RoomListNotFoundError: Se não encontrada ou de outra banda.
    """
    try:
        room_list = RoomList.objects.select_related('band', 'show').get(pk=room_list_id)
    except RoomList.DoesNotExist:
        raise RoomListNotFoundError("Room List não encontrada.")

    if room_list.band_id != band.id:
        raise RoomListNotFoundError("Room List não pertence a esta banda.")

    return room_list


def get_visible_room_list_for_user(room_list_id, user):
    """
    Obtém Room List respeitando visibilidade:
    - Produtores veem todas as Room Lists da sua banda.
    - Integrantes veem apenas PUBLICADA.

    Returns:
        RoomList

    Raises:
        RoomListNotFoundError: Se não encontrada, de outra banda, ou não visível.
    """
    try:
        room_list = RoomList.objects.select_related('band', 'show').get(pk=room_list_id)
    except RoomList.DoesNotExist:
        raise RoomListNotFoundError("Room List não encontrada.")

    if room_list.band_id != user.band_id:
        raise RoomListNotFoundError("Room List não pertence à banda do usuário.")

    if user.role == 'PRODUTOR':
        return room_list

    # Integrantes só veem publicadas
    if room_list.status != RoomList.StatusChoices.PUBLICADA:
        raise RoomListNotFoundError("Room List não disponível para visualização.")

    return room_list


def get_pending_issues(room_list):
    """
    Retorna relatório unificado de pendências para a Room List.

    Categorias:
      - 'no_room' (blocking): Participante precisa de hospedagem mas não tem quarto.
      - 'over_capacity' (blocking): Quarto com mais ocupantes que a capacidade.
      - 'capacity_type_mismatch' (blocking): Capacidade incompatível com tipo de quarto.
      - 'duplicate_room_number' (blocking): Número ou nome de quarto duplicado.
      - 'missing_room_name' (blocking): Quarto sem identificação útil.
      - 'room_wrong_list' (blocking): Quarto vinculado incorretamente.
      - 'inactive_integrante' (warning): Integrante com is_active=False.
      - 'removed_integrante' (warning): Participante sem referência ao integrante original.

    Returns:
        PendingIssuesReport
    """
    issues = []

    # 1. Participantes sem quarto que precisam de hospedagem (blocking)
    participants_no_room = room_list.participants.filter(
        room__isnull=True, needs_lodging=True
    ).select_related('original_integrante')
    for p in participants_no_room:
        name = p.snapshot_name or '(sem nome)'
        issues.append(PendingIssue(
            category='no_room',
            severity='blocking',
            description=f'Participante "{name}" precisa de hospedagem mas não está alocado em nenhum quarto.',
            related_object_id=p.pk,
            related_object_type='RoomListParticipant',
        ))

    # 2. Quartos acima da capacidade (blocking)
    rooms = room_list.rooms.all()
    for room in rooms:
        occupant_count = room.participants.count()
        if occupant_count > room.capacity:
            issues.append(PendingIssue(
                category='over_capacity',
                severity='blocking',
                description=f'Quarto "{room.number_or_name}" tem {occupant_count} ocupantes mas capacidade para {room.capacity}.',
                related_object_id=room.pk,
                related_object_type='Room',
            ))

    # 3. Capacidade incompatível com tipo exato (blocking)
    for room in rooms:
        if room.type not in Room.RoomTypeChoices.values:
            issues.append(PendingIssue(
                category='unknown_room_type',
                severity='blocking',
                description=f'Quarto "{room.number_or_name}" possui tipo desconhecido: "{room.type}".',
                related_object_id=room.pk,
                related_object_type='Room',
            ))
        elif room.type == Room.RoomTypeChoices.PERSONALIZADO:
            if room.capacity <= 0:
                issues.append(PendingIssue(
                    category='invalid_capacity',
                    severity='blocking',
                    description=f'Quarto "{room.number_or_name}" (PERSONALIZADO) exige capacidade positiva.',
                    related_object_id=room.pk,
                    related_object_type='Room',
                ))
        else:
            expected_cap = _CAPACITY_LIMITS.get(room.type)
            if expected_cap is not None:
                if room.type == Room.RoomTypeChoices.CASAL:
                    if room.capacity not in [1, 2]:
                        issues.append(PendingIssue(
                            category='capacity_type_mismatch',
                            severity='blocking',
                            description=f'Quarto "{room.number_or_name}" é do tipo {room.type} (exige 1 ou 2 ocupantes) mas tem capacidade {room.capacity}.',
                            related_object_id=room.pk,
                            related_object_type='Room',
                        ))
                elif room.capacity != expected_cap:
                    issues.append(PendingIssue(
                        category='capacity_type_mismatch',
                        severity='blocking',
                        description=f'Quarto "{room.number_or_name}" é do tipo {room.type} (exige {expected_cap}) mas tem capacidade {room.capacity}.',
                        related_object_id=room.pk,
                        related_object_type='Room',
                    ))

    # 4. Inconsistências defensivas nos quartos e participantes (blocking)
    names_seen = set()
    for room in rooms:
        name_clean = room.number_or_name.strip() if room.number_or_name else ''
        if not name_clean:
            issues.append(PendingIssue(
                category='missing_room_name',
                severity='blocking',
                description=f'Quarto ID {room.pk} está sem identificação/nome útil.',
                related_object_id=room.pk,
                related_object_type='Room',
            ))
        elif name_clean in names_seen:
            issues.append(PendingIssue(
                category='duplicate_room_number',
                severity='blocking',
                description=f'Número/nome de quarto duplicado: "{name_clean}".',
                related_object_id=room.pk,
                related_object_type='Room',
            ))
        else:
            names_seen.add(name_clean)

    participants_with_room = room_list.participants.filter(
        room__isnull=False
    ).select_related('room')
    for p in participants_with_room:
        if p.room.room_list_id != room_list.id:
            issues.append(PendingIssue(
                category='room_wrong_list',
                severity='blocking',
                description=f'Participante "{p.snapshot_name}" está em um quarto de outra Room List.',
                related_object_id=p.pk,
                related_object_type='RoomListParticipant',
            ))

    # 5. Integrantes inativos (warning)
    participants_with_integrante = room_list.participants.filter(
        original_integrante__isnull=False
    ).select_related('original_integrante')
    for p in participants_with_integrante:
        if not p.original_integrante.is_active:
            issues.append(PendingIssue(
                category='inactive_integrante',
                severity='warning',
                description=f'Integrante "{p.snapshot_name}" está inativo.',
                related_object_id=p.pk,
                related_object_type='RoomListParticipant',
            ))

    # 6. Integrantes removidos (warning)
    participants_removed = room_list.participants.filter(
        original_integrante__isnull=True
    )
    for p in participants_removed:
        issues.append(PendingIssue(
            category='removed_integrante',
            severity='warning',
            description=f'Participante "{p.snapshot_name}" não possui referência ao integrante original (pode ter sido removido).',
            related_object_id=p.pk,
            related_object_type='RoomListParticipant',
        ))

    return PendingIssuesReport(issues=issues)


def validate_room_list_for_publication(room_list):
    """
    Calcula pendências de publicação sem alterar nada.
    (Mesma implementação de get_pending_issues).
    """
    return get_pending_issues(room_list)


# ============================================================
# COMANDOS DE ROOM LIST
# ============================================================

@transaction.atomic
def create_room_list(show_id, band_id, user, hotel_name, city, **kwargs):
    """
    Cria Room List e popula participantes a partir da escala do show.

    Locks: Show (select_for_update) para serializar criação e garantir unicidade ativa.

    Raises:
        BandAccessDeniedError, ActiveRoomListExistsError, RoomListServiceError
    """
    try:
        locked_show = Show.objects.select_for_update().get(pk=show_id)
    except Show.DoesNotExist:
        raise RoomListServiceError("Show não encontrado.")

    if locked_show.band_id != band_id:
        raise RoomListServiceError("O show não pertence à banda informada.")

    band = locked_show.band
    validate_band_access(user, band)

    # Verificar unicidade ativa (depois do lock)
    active_exists = RoomList.objects.filter(
        show=locked_show,
        status__in=[RoomList.StatusChoices.RASCUNHO, RoomList.StatusChoices.PUBLICADA]
    ).exists()
    if active_exists:
        raise ActiveRoomListExistsError(
            "Já existe uma Room List ativa (rascunho ou publicada) para este show."
        )

    allowed_fields = {
        'address', 'contact', 'phone', 'reservation_code',
        'check_in', 'check_out', 'notes'
    }
    filtered_kwargs = {k: v for k, v in kwargs.items() if k in allowed_fields}

    room_list = RoomList(
        band=band,
        show=locked_show,
        hotel_name=hotel_name,
        city=city,
        **filtered_kwargs
    )
    room_list.full_clean()
    room_list.save()

    show_participants = ShowParticipant.objects.filter(
        show=locked_show
    ).select_related('integrante')

    participants_to_create = []
    for sp in show_participants:
        integrante = sp.integrante
        rlp = RoomListParticipant(
            room_list=room_list,
            original_integrante=integrante,
            order=sp.order,
            snapshot_name=integrante.name if integrante else sp.name,
            snapshot_cpf=integrante.cpf if integrante else '',
            snapshot_role=integrante.role if integrante else sp.role,
            snapshot_category=integrante.category if integrante else sp.category,
            needs_lodging=True,
        )
        rlp.full_clean()
        participants_to_create.append(rlp)

    RoomListParticipant.objects.bulk_create(participants_to_create)
    return room_list


@transaction.atomic
def sync_room_list_participants_from_show(room_list_id, user):
    """
    Sincroniza participantes da escala do show para a Room List,
    adicionando apenas os que ainda não estão presentes.

    Raises:
        BandAccessDeniedError, RoomListServiceError, ValidationError
    Returns:
        (room_list, added_count)
    """
    locked_rl = RoomList.objects.select_for_update().get(pk=room_list_id)
    validate_band_access(user, locked_rl.band)

    # Garantir consistência entre band do show e band da room list
    locked_rl.refresh_from_db()
    show = Show.objects.select_for_update().get(pk=locked_rl.show_id)
    if show.band_id != locked_rl.band_id:
        raise RoomListServiceError("Vínculo entre Show e Room List inconsistente.")

    existing_integrante_ids = set(
        locked_rl.participants.filter(original_integrante__isnull=False)
        .values_list('original_integrante_id', flat=True)
    )

    show_participants = ShowParticipant.objects.filter(
        show=show
    ).select_related('integrante')

    to_create = []
    for sp in show_participants:
        integrante = sp.integrante
        if integrante and integrante.pk in existing_integrante_ids:
            continue
        rlp = RoomListParticipant(
            room_list=locked_rl,
            original_integrante=integrante,
            order=sp.order,
            snapshot_name=integrante.name if integrante else getattr(sp, 'name', ''),
            snapshot_cpf=integrante.cpf if integrante else '',
            snapshot_role=integrante.role if integrante else getattr(sp, 'role', ''),
            snapshot_category=integrante.category if integrante else getattr(sp, 'category', 'MUSICO'),
            needs_lodging=True,
        )
        rlp.full_clean()
        to_create.append(rlp)

    RoomListParticipant.objects.bulk_create(to_create)
    locked_rl.refresh_from_db()
    return locked_rl, len(to_create)


@transaction.atomic
def update_room_list(room_list_id, user, **kwargs):
    """
    Atualiza dados do hotel.

    Locks: RoomList (select_for_update).
    Campos permitidos: hotel_name, city, address, contact, phone,
                       reservation_code, check_in, check_out, notes.

    Raises:
        BandAccessDeniedError, RoomListNotFoundError,
        RoomListArchivedError, RoomListPublishedError
    """
    locked_rl = RoomList.objects.select_for_update().get(pk=room_list_id)
    validate_band_access(user, locked_rl.band)
    _assert_room_list_editable(locked_rl)

    allowed_fields = {
        'hotel_name', 'city', 'address', 'contact', 'phone',
        'reservation_code', 'check_in', 'check_out', 'notes'
    }

    changed = False
    for key, value in kwargs.items():
        if key not in allowed_fields:
            raise RoomListServiceError(
                f"O campo '{key}' não pode ser alterado por este serviço."
            )
        if getattr(locked_rl, key) != value:
            setattr(locked_rl, key, value)
            changed = True

    locked_rl.full_clean()
    if not changed:
        return locked_rl

    locked_rl.content_revision += 1
    locked_rl.save(update_fields=['hotel_name', 'city', 'address', 'contact', 'phone', 'reservation_code', 'check_in', 'check_out', 'notes', 'content_revision', 'updated_at'])
    return locked_rl


@transaction.atomic
def publish_room_list(room_list_id, user):
    """
    Publica a Room List após verificação de pendências bloqueantes.

    Locks: RoomList (select_for_update).
    Transição: RASCUNHO → PUBLICADA.

    Raises:
        BandAccessDeniedError, RoomListNotFoundError,
        RoomListArchivedError, RoomListPublishedError, PublicationBlockedError
    """
    locked_rl = RoomList.objects.select_for_update().get(pk=room_list_id)
    validate_band_access(user, locked_rl.band)

    if locked_rl.status == RoomList.StatusChoices.ARQUIVADA:
        raise RoomListArchivedError("Não é possível publicar uma Room List arquivada.")
    if locked_rl.status == RoomList.StatusChoices.PUBLICADA:
        raise RoomListPublishedError("Room List já está publicada.")

    # Verificar pendências sob lock
    report = get_pending_issues(locked_rl)
    if report.has_blocking:
        raise PublicationBlockedError(
            "Existem pendências bloqueantes que impedem a publicação.",
            pending_issues=report,
        )

    locked_rl.status = RoomList.StatusChoices.PUBLICADA
    locked_rl.published_at = timezone.now()
    locked_rl.published_by = user
    locked_rl.save()
    return locked_rl


@transaction.atomic
def reopen_room_list(room_list_id, user):
    """
    Reabre uma Room List publicada para edição.

    Locks: RoomList (select_for_update).
    Transição: PUBLICADA → RASCUNHO.

    Raises:
        BandAccessDeniedError, RoomListServiceError
    """
    locked_rl = RoomList.objects.select_for_update().get(pk=room_list_id)
    validate_band_access(user, locked_rl.band)

    if locked_rl.status != RoomList.StatusChoices.PUBLICADA:
        raise RoomListServiceError(
            "Somente Room Lists publicadas podem ser reabertas."
        )

    locked_rl.status = RoomList.StatusChoices.RASCUNHO
    locked_rl.save()
    return locked_rl

@transaction.atomic
def reactivate_room_list(room_list_id, user):
    """
    Reativa uma Room List arquivada.

    Locks: RoomList (select_for_update).
    Transição: ARQUIVADA -> RASCUNHO.

    Raises:
        BandAccessDeniedError, RoomListServiceError
    """
    locked_rl = RoomList.objects.select_for_update().get(pk=room_list_id)
    validate_band_access(user, locked_rl.band)

    if locked_rl.status != RoomList.StatusChoices.ARQUIVADA:
        raise RoomListServiceError(
            "Somente Room Lists arquivadas podem ser reativadas."
        )

    locked_rl.status = RoomList.StatusChoices.RASCUNHO
    locked_rl.save()
    return locked_rl


@transaction.atomic
def archive_room_list(room_list_id, user):
    """
    Arquiva a Room List, congelando edições.

    Locks: RoomList (select_for_update).
    Transição: RASCUNHO → ARQUIVADA ou PUBLICADA → ARQUIVADA.

    Raises:
        BandAccessDeniedError, RoomListArchivedError
    """
    locked_rl = RoomList.objects.select_for_update().get(pk=room_list_id)
    validate_band_access(user, locked_rl.band)

    if locked_rl.status == RoomList.StatusChoices.ARQUIVADA:
        raise RoomListArchivedError("Room List já está arquivada.")

    locked_rl.status = RoomList.StatusChoices.ARQUIVADA
    locked_rl.archived_at = timezone.now()
    locked_rl.archived_by = user
    locked_rl.save()
    return locked_rl


@transaction.atomic
def mark_room_list_as_sent(room_list_id, user):
    """
    Registra o envio da Room List ao hotel.

    Locks: RoomList (select_for_update).
    Pré-condição: status == PUBLICADA.

    Raises:
        BandAccessDeniedError, RoomListServiceError
    """
    locked_rl = RoomList.objects.select_for_update().get(pk=room_list_id)
    validate_band_access(user, locked_rl.band)

    if locked_rl.status != RoomList.StatusChoices.PUBLICADA:
        raise RoomListServiceError(
            "Somente Room Lists publicadas podem ser marcadas como enviadas."
        )

    locked_rl.last_sent_to_hotel_at = timezone.now()
    locked_rl.last_sent_by = user
    locked_rl.last_sent_revision = locked_rl.content_revision
    locked_rl.save()
    return locked_rl


@transaction.atomic
def delete_room_list(room_list_id, user):
    """
    Exclui uma Room List em rascunho ou arquivada.

    Locks: RoomList (select_for_update).
    Pré-condição: status in (RASCUNHO, ARQUIVADA).

    Raises:
        BandAccessDeniedError, RoomListServiceError
    """
    locked_rl = RoomList.objects.select_for_update().get(pk=room_list_id)
    validate_band_access(user, locked_rl.band)

    if locked_rl.status not in [RoomList.StatusChoices.RASCUNHO, RoomList.StatusChoices.ARQUIVADA]:
        raise RoomListServiceError(
            "Somente Room Lists em rascunho ou arquivadas podem ser excluídas."
        )

    locked_rl.delete()


@transaction.atomic
def add_integrantes_to_room_list(room_list_id, user, integrantes_ids):
    """
    Adiciona integrantes selecionados à Room List, sem remover nenhum existente.

    Locks: Show (select_for_update), depois RoomList (select_for_update).

    Returns:
        tuple(RoomList, int): Room List atualizada e quantidade de participantes adicionados.

    Raises:
        BandAccessDeniedError, RoomListNotEditableError, RoomListServiceError
    """
    try:
        rl_initial = RoomList.objects.only('show_id').get(pk=room_list_id)
    except RoomList.DoesNotExist:
        raise RoomListNotFoundError("Room List não encontrada.")

    locked_show = Show.objects.select_for_update().get(pk=rl_initial.show_id)
    validate_band_access(user, locked_show.band)

    locked_rl = RoomList.objects.select_for_update().select_related('band').get(pk=room_list_id)

    if locked_rl.show_id != locked_show.id or locked_rl.band_id != locked_show.band_id:
        raise RoomListServiceError("Vínculo entre Show e Room List inconsistente.")

    validate_band_access(user, locked_rl.band)
    _assert_room_list_editable(locked_rl)

    existing_integrante_ids = set(
        locked_rl.participants.filter(
            original_integrante__isnull=False
        ).values_list('original_integrante_id', flat=True)
    )

    from core.models import Integrante
    integrantes = Integrante.objects.filter(
        band=locked_rl.band,
        is_active=True,
        id__in=integrantes_ids
    )

    participants_to_create = []
    for integrante in integrantes:
        if integrante.id not in existing_integrante_ids:
            rlp = RoomListParticipant(
                room_list=locked_rl,
                original_integrante=integrante,
                order=0,
                snapshot_name=integrante.name,
                snapshot_cpf=integrante.cpf,
                snapshot_role=integrante.role,
                snapshot_category=integrante.category,
                needs_lodging=True,
            )
            rlp.full_clean()
            participants_to_create.append(rlp)

    added = len(participants_to_create)
    if added > 0:
        RoomListParticipant.objects.bulk_create(participants_to_create)
        locked_rl.content_revision += 1
        locked_rl.save(update_fields=['content_revision'])

    return locked_rl, added


# ============================================================
# COMANDOS DE QUARTOS
# ============================================================

@transaction.atomic
def create_room(room_list_id, room_type, capacity, number_or_name, user, **kwargs):
    """
    Cria um quarto na Room List.

    Locks: RoomList (select_for_update).

    Raises:
        BandAccessDeniedError, RoomListNotEditableError,
        RoomCapacityTypeMismatchError, DuplicateRoomNumberError
    """
    locked_rl = RoomList.objects.select_for_update().get(pk=room_list_id)
    validate_band_access(user, locked_rl.band)
    _assert_room_list_editable(locked_rl)

    validate_room_capacity_for_type(room_type, capacity)

    number_or_name = number_or_name.strip() if number_or_name else number_or_name

    if Room.objects.filter(room_list=locked_rl, number_or_name=number_or_name).exists():
        raise DuplicateRoomNumberError(f"Já existe um quarto '{number_or_name}' nesta Room List.")

    allowed_kwargs = {k: v for k, v in kwargs.items() if k in {'beds_config', 'has_ac', 'order'}}

    room = Room(
        room_list=locked_rl,
        type=room_type,
        capacity=capacity,
        number_or_name=number_or_name,
        **allowed_kwargs
    )
    room.full_clean()

    try:
        with transaction.atomic():
            room.save()
    except IntegrityError as exc:
        raise

    locked_rl.content_revision += 1
    locked_rl.save(update_fields=['content_revision', 'updated_at'])
    return room


@transaction.atomic
def update_room(room_id, room_list_id, user, **kwargs):
    """
    Atualiza um quarto verificando capacidade sob lock.

    Locks: RoomList, depois Room.
    Campos permitidos: number_or_name, type, capacity, beds_config, has_ac, order.

    Raises:
        BandAccessDeniedError, RoomListNotEditableError,
        RoomOverCapacityError, RoomCapacityTypeMismatchError, DuplicateRoomNumberError
    """
    locked_rl = RoomList.objects.select_for_update().get(pk=room_list_id)
    validate_band_access(user, locked_rl.band)
    _assert_room_list_editable(locked_rl)

    locked_room = Room.objects.select_for_update().get(pk=room_id, room_list=locked_rl)

    allowed_fields = {'number_or_name', 'type', 'capacity', 'beds_config', 'has_ac', 'order'}

    final_type = kwargs.get('type', locked_room.type)
    final_capacity = kwargs.get('capacity', locked_room.capacity)

    validate_room_capacity_for_type(final_type, final_capacity)

    if 'capacity' in kwargs:
        current_occupants = locked_room.participants.count()
        if kwargs['capacity'] < current_occupants:
            raise RoomOverCapacityError(
                f"A nova capacidade ({kwargs['capacity']}) é menor que o número de "
                f"ocupantes atuais ({current_occupants})."
            )

    if 'number_or_name' in kwargs:
        new_name = kwargs['number_or_name'].strip() if kwargs['number_or_name'] else kwargs['number_or_name']
        kwargs['number_or_name'] = new_name
        if Room.objects.filter(
            room_list=locked_rl, number_or_name=new_name
        ).exclude(pk=locked_room.pk).exists():
            raise DuplicateRoomNumberError(
                f"Já existe outro quarto '{new_name}' nesta Room List."
            )

    changed = False
    for key, value in kwargs.items():
        if key not in allowed_fields:
            raise RoomListServiceError(
                f"O campo '{key}' não pode ser alterado neste serviço."
            )
        if getattr(locked_room, key) != value:
            setattr(locked_room, key, value)
            changed = True

    locked_room.full_clean()

    if not changed:
        return locked_room

    try:
        with transaction.atomic():
            locked_room.save()
    except IntegrityError as exc:
        if Room.objects.filter(room_list=locked_rl, number_or_name=locked_room.number_or_name).exclude(pk=locked_room.pk).exists():
            raise DuplicateRoomNumberError(
                "Conflito de integridade ao atualizar quarto."
            ) from exc
        raise

    locked_rl.content_revision += 1
    locked_rl.save(update_fields=['content_revision', 'updated_at'])

    return locked_room


@transaction.atomic
def delete_room(room_id, room_list_id, user):
    """
    Exclui um quarto. Participantes passam a room=None via SET_NULL do banco.

    Locks: RoomList, depois Room.

    Raises:
        BandAccessDeniedError, RoomListNotEditableError
    """
    locked_rl = RoomList.objects.select_for_update().get(pk=room_list_id)
    validate_band_access(user, locked_rl.band)
    _assert_room_list_editable(locked_rl)

    room = Room.objects.select_for_update().get(pk=room_id, room_list=locked_rl)
    room.delete()

    locked_rl.content_revision += 1
    locked_rl.save(update_fields=['content_revision', 'updated_at'])


# ============================================================
# COMANDOS DE PARTICIPANTES
# ============================================================

@transaction.atomic
def assign_participant_to_room(room_list_participant_id, room_id, user):
    """
    Aloca participante ao quarto verificando capacidade sob lock.

    Locks: RoomList, depois RoomListParticipant (releitura), depois Room(s) por pk crescente, depois RoomListParticipant (lock final).
    Idempotente: se já está no quarto de destino, retorna sem alterar.

    Raises:
        BandAccessDeniedError, RoomListNotEditableError,
        RoomOverCapacityError, RoomListServiceError
    """
    try:
        rlp_initial = RoomListParticipant.objects.select_related('room_list').get(
            pk=room_list_participant_id
        )
    except RoomListParticipant.DoesNotExist:
        raise RoomListServiceError("Participante não encontrado.")

    locked_rl = RoomList.objects.select_for_update().get(pk=rlp_initial.room_list_id)
    validate_band_access(user, locked_rl.band)
    _assert_room_list_editable(locked_rl)

    rlp_fresh = RoomListParticipant.objects.get(pk=room_list_participant_id)

    room_ids = sorted(set(filter(None, [rlp_fresh.room_id, room_id])))
    locked_rooms = {
        r.pk: r
        for r in Room.objects.select_for_update().filter(pk__in=room_ids).order_by('pk')
    }

    if rlp_fresh.room_id is not None:
        source_room = locked_rooms.get(rlp_fresh.room_id)
        if not source_room or source_room.room_list_id != locked_rl.pk:
            raise RoomListServiceError("Quarto de origem não encontrado ou de outra Room List.")

    target_room = locked_rooms.get(room_id)
    if not target_room:
        raise RoomListServiceError("Quarto não encontrado.")

    if target_room.room_list_id != locked_rl.pk:
        raise RoomListServiceError("Quarto não pertence à mesma Room List.")

    locked_rlp = RoomListParticipant.objects.select_for_update().get(
        pk=room_list_participant_id
    )

    if locked_rlp.room_id != rlp_fresh.room_id:
        raise RoomListServiceError("O estado do participante foi alterado por outra transação.")

    if locked_rlp.room_list_id != locked_rl.pk:
        raise RoomListServiceError("Participante não pertence a esta Room List.")

    if locked_rlp.room_id == room_id:
        return locked_rlp

    validate_room_capacity_for_type(target_room.type, target_room.capacity)

    current_occupants = target_room.participants.count()
    if current_occupants >= target_room.capacity:
        raise RoomOverCapacityError("O quarto já atingiu sua capacidade máxima.")

    locked_rlp.room = target_room
    locked_rlp.needs_lodging = True
    locked_rlp.full_clean()
    locked_rlp.save(update_fields=['room', 'needs_lodging', 'updated_at'])

    locked_rl.content_revision += 1
    locked_rl.save(update_fields=['content_revision', 'updated_at'])
    return locked_rlp


@transaction.atomic
def unassign_participant(room_list_participant_id, user, needs_lodging=True):
    """
    Desaloca participante de seu quarto.

    Locks: RoomList, depois RoomListParticipant.
    Idempotente: se já sem quarto e needs_lodging igual, retorna sem alterar.

    Raises:
        BandAccessDeniedError, RoomListNotEditableError
    """
    try:
        rlp = RoomListParticipant.objects.select_related('room_list').get(
            pk=room_list_participant_id
        )
    except RoomListParticipant.DoesNotExist:
        raise RoomListServiceError("Participante não encontrado.")

    locked_rl = RoomList.objects.select_for_update().get(pk=rlp.room_list_id)
    validate_band_access(user, locked_rl.band)
    _assert_room_list_editable(locked_rl)

    locked_rlp = RoomListParticipant.objects.select_for_update().get(
        pk=room_list_participant_id
    )

    if locked_rlp.room is None and locked_rlp.needs_lodging == needs_lodging:
        return locked_rlp

    locked_rlp.room = None
    locked_rlp.needs_lodging = needs_lodging
    locked_rlp.full_clean()
    locked_rlp.save(update_fields=['room', 'needs_lodging', 'updated_at'])

    locked_rl.content_revision += 1
    locked_rl.save(update_fields=['content_revision', 'updated_at'])
    return locked_rlp


# ============================================================
# APLICAÇÃO DO PADRÃO
# ============================================================

@transaction.atomic
def apply_template_to_room_list(room_list_id, user):
    """
    Aplica o LodgingTemplate da banda à Room List.

    Locks: RoomList (select_for_update).
    Pré-condições: RASCUNHO, sem quartos, sem alocações,
                   banda possui LodgingTemplate.

    Raises:
        BandAccessDeniedError, RoomListNotEditableError, RoomListServiceError
    """
    locked_rl = RoomList.objects.select_for_update().select_related(
        'band'
    ).get(pk=room_list_id)
    validate_band_access(user, locked_rl.band)
    _assert_room_list_editable(locked_rl)

    try:
        template = LodgingTemplate.objects.get(band=locked_rl.band)
    except LodgingTemplate.DoesNotExist:
        raise RoomListServiceError(
            "Não existe modelo de hospedagem configurado para esta banda."
        )

    if locked_rl.rooms.exists():
        raise RoomListServiceError(
            "A Room List já possui quartos. Não é possível aplicar o modelo."
        )
    if locked_rl.participants.filter(room__isnull=False).exists():
        raise RoomListServiceError(
            "A Room List já possui alocações. Não é possível aplicar o modelo."
        )

    template_rooms = template.rooms.all().order_by('order', 'pk')

    rooms_to_create = []
    room_mapping = {}
    for idx, t_room in enumerate(template_rooms, start=1):
        validate_room_capacity_for_type(t_room.type, t_room.capacity)
        number_or_name = t_room.number_or_name if t_room.number_or_name else f"Quarto {idx}"
        room = Room(
            room_list=locked_rl,
            number_or_name=number_or_name,
            type=t_room.type,
            capacity=t_room.capacity,
            beds_config=t_room.beds_config,
            has_ac=t_room.has_ac,
            order=t_room.order,
        )
        room.full_clean()
        rooms_to_create.append(room)
        room_mapping[t_room.pk] = room

    template_participants = TemplateParticipant.objects.filter(
        template=template
    ).select_related('original_integrante')

    rlp_dict = {
        rlp.original_integrante_id: rlp
        for rlp in locked_rl.participants.all() if rlp.original_integrante_id
    }

    participants_to_update = []
    room_occupancy_by_troom = {t.pk: 0 for t in template_rooms}
    for t_part in template_participants:
        if t_part.room_id not in room_mapping:
            continue

        rlp = rlp_dict.get(t_part.original_integrante_id)
        if not rlp:
            continue

        target_room = room_mapping[t_part.room_id]
        room_occupancy_by_troom[t_part.room_id] += 1

        if room_occupancy_by_troom[t_part.room_id] > target_room.capacity:
            raise RoomOverCapacityError("O quarto já atingiu sua capacidade máxima.")

        rlp.room = target_room
        rlp.full_clean(exclude=["room"])
        if target_room.room_list_id != locked_rl.pk:
            raise RoomListServiceError("Quarto planejado não pertence à mesma Room List.")

        participants_to_update.append((rlp, target_room))

    # Persistir tudo só após todas as validações passarem
    Room.objects.bulk_create(rooms_to_create)
    for rlp, target_room in participants_to_update:
        rlp.room = target_room
        rlp.full_clean()
        rlp.save(update_fields=['room', 'updated_at'])

    locked_rl.content_revision += 1
    locked_rl.save(update_fields=['content_revision', 'updated_at'])
    return locked_rl


@transaction.atomic
def create_or_replace_lodging_template(band_id, rooms_payload, user):
    """
    Cria ou substitui integralmente o modelo padrão de hospedagem da banda.

    rooms_payload: list de dicts com o formato:
    [
        {
            "type": "INDIVIDUAL",
            "capacity": 1,
            "beds_config": "1 cama", # Opcional
            "has_ac": True,          # Opcional, default True
            "participants": [1, 2]   # Lista de IDs de integrantes
        },
        ...
    ]
    """
    band = Band.objects.select_for_update().get(pk=band_id)
    validate_band_access(user, band)

    if not isinstance(rooms_payload, list):
        raise RoomListServiceError("O payload de quartos deve ser uma lista.")
    if not rooms_payload:
        raise RoomListServiceError("O payload de quartos não pode ser vazio.")

    seen_integrantes = set()
    integrantes_needed = set()

    # Validação prévia (Fail-fast)
    for room_data in rooms_payload:
        room_type = room_data.get('type')
        capacity = room_data.get('capacity')

        if not room_type or capacity is None:
            raise RoomListServiceError("Cada quarto deve informar 'type' e 'capacity'.")

        try:
            capacity = int(capacity)
        except ValueError:
            from django.core.exceptions import ValidationError
            raise ValidationError({'capacity': 'Capacidade deve ser um número inteiro.'})

        if capacity <= 0:
            from django.core.exceptions import ValidationError
            raise ValidationError({'capacity': 'Capacidade deve ser maior que zero.'})

        validate_room_capacity_for_type(room_type, capacity)

        participants = room_data.get('participants', [])
        if not isinstance(participants, list):
            raise RoomListServiceError("participants deve ser uma lista de IDs.")

        if len(participants) > capacity:
            raise RoomOverCapacityError(f"Quarto do tipo {room_type} estourou a capacidade de {capacity}.")

        for integrante_id in participants:
            if integrante_id in seen_integrantes:
                raise RoomListServiceError(f"Integrante ID {integrante_id} duplicado no payload.")
            seen_integrantes.add(integrante_id)
            integrantes_needed.add(integrante_id)

    # Validar a existência e vínculo dos integrantes num só query
    if integrantes_needed:
        found_integrantes = set(Integrante.objects.filter(
            band=band, id__in=integrantes_needed
        ).values_list('id', flat=True))

        missing = integrantes_needed - found_integrantes
        if missing:
            raise RoomListServiceError(f"Integrantes inválidos ou pertencentes a outra banda: {missing}")

    # Exclusão do modelo antigo e seus filhos
    try:
        old_template = LodgingTemplate.objects.get(band=band)
        old_template.delete()
    except LodgingTemplate.DoesNotExist:
        pass

    # Criação do novo modelo
    template = LodgingTemplate.objects.create(band=band)

    for room_order, room_data in enumerate(rooms_payload, start=1):
        t_room = TemplateRoom.objects.create(
            template=template,
            type=room_data.get('type'),
            capacity=int(room_data.get('capacity')),
            beds_config=room_data.get('beds_config', ''),
            has_ac=room_data.get('has_ac', True),
            order=room_order
        )

        participants = room_data.get('participants', [])
        for p_order, integrante_id in enumerate(participants, start=1):
            TemplateParticipant.objects.create(
                template=template,
                room=t_room,
                original_integrante_id=integrante_id,
                order=p_order
            )

    return template


@transaction.atomic
def delete_lodging_template(band_id, user):
    """
    Exclui o LodgingTemplate da banda e todos os seus filhos.

    Retorna True se deletou, False se não existia.
    """
    band = Band.objects.select_for_update().get(pk=band_id)
    validate_band_access(user, band)

    try:
        template = LodgingTemplate.objects.get(band=band)
        template.delete()
        return True
    except LodgingTemplate.DoesNotExist:
        return False
