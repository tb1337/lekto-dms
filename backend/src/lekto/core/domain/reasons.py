"""Why a check came out as it did, or a rule's action did not act: a code with parameters
(issue #83). Clients translate the code (the web UI with its messages); the English text stays
for the API, the processing log and the language model.

Every code has an English template (`TEMPLATES`) that names its parameters as `{name}`; a
parameter may name its kind after a colon (`KINDS`), which says how it is written: `{names:or}`
a list of names, quoted and joined by "or", `{date:date}` a day in ISO 8601, `{share:percent}`
a fraction as a percentage, `{value:value}` a field's value as a reason shows it (yes or no,
none, or the text). A parameter without a kind is text. `Reason.text` renders the template;
`catalog` lists the codes with their parameters and kinds for the clients (the OpenAPI
document).

A reason may be about a custom field (`subject`, its name: "'Amount': the amount does not
appear in the text"), come from a rule (`rule`, its name), or, among a node's reasons, be about
one of the built-in check fields (`field`: "contact: no contact recognised"). `TEXT` is a
reason as written: by a person (a review a rule forces, a migration plan's), or stored before
reasons had codes.
"""

import json
import string
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Self

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.json_value import JsonObject, JsonValue, as_object, as_text


class ReasonCode(StrEnum):
    TEXT = "text"
    ERROR = "error"
    # contact, document type, topic (the judge)
    SIGNALS_DISAGREE = "signals_disagree"
    ONLY_SUGGESTED = "only_suggested"
    ONE_SIGNAL_ONLY = "one_signal_only"
    ONLY_IDENTIFIER = "only_identifier"
    CONTACT_IS_RECIPIENT = "contact_is_recipient"
    CONTACT_IDENTIFIERS_SEVERAL = "contact_identifiers_several"
    CONTACT_NEW_PROPOSED = "contact_new_proposed"
    CONTACT_NONE = "contact_none"
    CONTACT_NONE_NO_MODEL = "contact_none_no_model"
    CONTACT_NOT_IN_TEXT = "contact_not_in_text"
    SENDER_NOT_A_CONTACT = "sender_not_a_contact"
    SENDER_MATCHES_SEVERAL = "sender_matches_several"
    SENDER_ONLY_SIMILAR = "sender_only_similar"
    TYPE_NEW_PROPOSED = "type_new_proposed"
    TYPE_NONE = "type_none"
    TOPIC_WITHOUT_CONTACT = "topic_without_contact"
    TOPIC_NONE = "topic_none"
    TOPIC_CONTACT_SUGGESTED = "topic_contact_suggested"
    # space (the judge)
    SPACE_CHOSEN_BY_PERSON = "space_chosen_by_person"
    SPACE_NAMED_UNSEEN = "space_named_unseen"
    SPACE_STAYS_FOR_NAMED = "space_stays_for_named"
    SPACE_SHOWS_MORE = "space_shows_more"
    SPACE_HAND_OVER = "space_hand_over"
    SPACE_UPLOADER_UNSEEN = "space_uploader_unseen"
    SPACE_OTHER = "space_other"
    SPACES_DISAGREE = "spaces_disagree"
    # dates, periods and field values (the judge and the fields node)
    DATE_NONE = "date_none"
    DATE_NONE_FROM_MODEL = "date_none_from_model"
    NOT_A_DATE = "not_a_date"
    DATE_IMPLAUSIBLE = "date_implausible"
    SAME_AS_DOCUMENT_DATE = "same_as_document_date"
    NOT_A_PERIOD = "not_a_period"
    PERIOD_IMPLAUSIBLE = "period_implausible"
    PERIOD_NO_YEAR = "period_no_year"
    SAME_DAY_AS_DOCUMENT_DATE = "same_day_as_document_date"
    FIELD_SET_BY_HAND = "field_set_by_hand"
    FIELD_BY_HAND_MISSING = "field_by_hand_missing"
    FIELD_NOT_FOUND = "field_not_found"
    FIELD_NOT_READ_NO_MODEL = "field_not_read_no_model"
    VALUE_INVALID = "value_invalid"
    QUOTE_NOT_IN_TEXT = "quote_not_in_text"
    QUOTE_MISSING = "quote_missing"
    QUOTE_WITHOUT_VALUE = "quote_without_value"
    QUOTE_TOO_SHORT = "quote_too_short"
    DATE_NOT_IN_TEXT = "date_not_in_text"
    PERIOD_NOT_IN_TEXT = "period_not_in_text"
    AMOUNT_NOT_IN_TEXT = "amount_not_in_text"
    CURRENCY_NOT_IN_TEXT = "currency_not_in_text"
    NUMBER_NOT_IN_TEXT = "number_not_in_text"
    LINK_NOT_IN_TEXT = "link_not_in_text"
    TEXT_NOT_IN_TEXT = "text_not_in_text"
    VALUE_READ_UNSURE = "value_read_unsure"
    PAGE_POORLY_READ = "page_poorly_read"
    PAGE_POORLY_READ_CONTENT = "page_poorly_read_content"
    SURROUNDINGS_POORLY_READ = "surroundings_poorly_read"
    # metadata taken over from another system
    SOURCE_LACKS_CONTACT = "source_lacks_contact"
    SOURCE_LACKS_DOCUMENT_TYPE = "source_lacks_document_type"
    SOURCE_LACKS_DOCUMENT_DATE = "source_lacks_document_date"
    PAPERLESS_USER_REVIEW = "paperless_user_review"
    PAPERLESS_CORRESPONDENT_REVIEW = "paperless_correspondent_review"
    PAPERLESS_DOCUMENT_TYPE_REVIEW = "paperless_document_type_review"
    PAPERLESS_TAG_REVIEW = "paperless_tag_review"
    PAPERLESS_CUSTOM_FIELD_REVIEW = "paperless_custom_field_review"
    PAPERLESS_STORAGE_PATH_REVIEW = "paperless_storage_path_review"
    PAPERLESS_ASN_REVIEW = "paperless_asn_review"
    # rules
    FIELD_DOES_NOT_APPLY = "field_does_not_apply"
    FIELD_GONE = "field_gone"
    CONTACT_GONE = "contact_gone"
    DOCUMENT_TYPE_GONE = "document_type_gone"
    TOPIC_GONE = "topic_gone"
    TAG_GONE = "tag_gone"
    SPACE_GONE = "space_gone"
    TAG_IS_GROUP = "tag_is_group"
    RULE_OTHER_SPACE = "rule_other_space"
    SPACE_NO_RIGHT_ANY_MORE = "space_no_right_any_more"
    SPACE_NO_RIGHT = "space_no_right"
    SPACE_WIDENS_UNCONFIRMED = "space_widens_unconfirmed"
    SPACE_WIDENS_NEEDS_CONFIRMED = "space_widens_needs_confirmed"
    REVIEW_ON_ARRIVAL_ONLY = "review_on_arrival_only"
    REVIEW_CONFIRMED = "review_confirmed"
    RULES_DISAGREE = "rules_disagree"
    VALUE_OTHER_NOT_ACCEPTED = "value_other_not_accepted"
    PERSON_DECIDED_FIELD = "person_decided_field"
    RULE_VALUE_ON_UNCONFIRMED = "rule_value_on_unconfirmed"
    MODEL_VALUE_OTHER = "model_value_other"
    RULES_VALUE_ON_UNCONFIRMED = "rules_value_on_unconfirmed"
    RULES_MODEL_VALUE_OTHER = "rules_model_value_other"
    TOPIC_PERSON_CHOSE = "topic_person_chose"
    TOPIC_NO_CONTACT = "topic_no_contact"
    TOPIC_NOT_ENABLED = "topic_not_enabled"
    TAG_ADDED_AND_REMOVED = "tag_added_and_removed"
    TAG_REMOVED_BY_PERSON = "tag_removed_by_person"
    TAG_SET_BY_PERSON = "tag_set_by_person"
    TAG_ABOVE_KEPT = "tag_above_kept"
    TITLE_EMPTY = "title_empty"
    TITLE_YIELDS = "title_yields"
    VALUE_EMPTY = "value_empty"
    TEMPLATE_MISSING_VALUE = "template_missing_value"
    # nodes: failures, notes, abstaining signals
    NODE_ATTEMPTS_EXHAUSTED = "node_attempts_exhausted"
    NODE_CRASHED = "node_crashed"
    FILE_NOT_PDF_OR_IMAGE = "file_not_pdf_or_image"
    FILE_DAMAGED = "file_damaged"
    FILE_NOT_PROCESSABLE = "file_not_processable"
    PDF_ENCRYPTED = "pdf_encrypted"
    PDF_UNREADABLE = "pdf_unreadable"
    PDF_UNREADABLE_DETAIL = "pdf_unreadable_detail"
    IMAGE_UNREADABLE = "image_unreadable"
    IMAGE_UNREADABLE_DETAIL = "image_unreadable_detail"
    DOCUMENT_NO_PAGES = "document_no_pages"
    OCR_FAILED = "ocr_failed"
    TEXT_UNREADABLE = "text_unreadable"
    SIGNATURE_DROPPED = "signature_dropped"
    COLOURS_CONVERTED = "colours_converted"
    NOT_PDFA = "not_pdfa"
    ARCHIVE_NOT_PDFA = "archive_not_pdfa"
    VISION_READ = "vision_read"
    VISION_NOT_CONFIGURED = "vision_not_configured"
    NO_TEXT = "no_text"
    ANSWER_UNFIT = "answer_unfit"
    NOTHING_RECOGNISED = "nothing_recognised"
    MASTER_DATA_CHANGED = "master_data_changed"
    METADATA_UNFIT = "metadata_unfit"
    TAKEN_OVER = "taken_over"
    SPACE_CHANGED_MEANWHILE = "space_changed_meanwhile"
    RULES_BACK_AND_FORTH = "rules_back_and_forth"
    RULES_CHANGE_UNFIT = "rules_change_unfit"
    SIGNAL_DID_NOT_RUN = "signal_did_not_run"
    NO_LANGUAGE_MODEL = "no_language_model"
    NO_DOCUMENT_TEXT = "no_document_text"
    NO_CLASSIFIER = "no_classifier"
    CLASSIFIER_UNUSABLE = "classifier_unusable"
    CLASSIFIER_UNTRAINED = "classifier_untrained"
    NEIGHBOURS_OFF = "neighbours_off"
    NO_EMBEDDING_INDEX = "no_embedding_index"
    TEXT_NOT_EMBEDDED = "text_not_embedded"
    VECTOR_MISFIT = "vector_misfit"
    NO_UPLOADER = "no_uploader"
    INDEX_UNAVAILABLE = "index_unavailable"
    NO_SIMILAR = "no_similar"
    # problems: requests the API refuses
    INPUT_MISSING = "input_missing"
    INPUT_TOO_SHORT = "input_too_short"
    INPUT_TOO_LONG = "input_too_long"
    INPUT_TOO_FEW = "input_too_few"
    INPUT_TOO_MANY = "input_too_many"
    INPUT_TOO_SMALL = "input_too_small"
    INPUT_ABOVE = "input_above"
    INPUT_TOO_LARGE = "input_too_large"
    INPUT_BELOW = "input_below"
    INPUT_CHOICE = "input_choice"
    INPUT_NOT_ID = "input_not_id"
    INPUT_NOT_DATE = "input_not_date"
    INPUT_NOT_DATETIME = "input_not_datetime"
    INPUT_NOT_NUMBER = "input_not_number"
    INPUT_NOT_INTEGER = "input_not_integer"
    INPUT_NOT_BOOLEAN = "input_not_boolean"
    INPUT_NOT_TEXT = "input_not_text"
    INPUT_NOT_LIST = "input_not_list"
    INPUT_NOT_OBJECT = "input_not_object"
    INPUT_UNKNOWN = "input_unknown"
    INPUT_PATTERN = "input_pattern"
    INPUT_INVALID = "input_invalid"
    IN_USE = "in_use"
    NAME_TAKEN = "name_taken"
    TOPIC_CARRIED = "topic_carried"
    CHOICES_IN_USE = "choices_in_use"
    VALUES_OUTSIDE_SCOPE = "values_outside_scope"
    TITLE_PATTERN_USES_FIELD = "title_pattern_uses_field"
    TYPE_HAS_VALUES = "type_has_values"
    TAG_HAS_CHILDREN = "tag_has_children"
    TAG_HAS_CONTACTS = "tag_has_contacts"
    TAG_HAS_TYPES = "tag_has_types"
    TOPIC_ENABLED_BY = "topic_enabled_by"
    TAG_USED_BY_RULES = "tag_used_by_rules"
    FIELD_USED_BY_PATTERNS = "field_used_by_patterns"
    FIELD_USED_BY_RULES = "field_used_by_rules"
    FIELD_KEY_TAKEN = "field_key_taken"
    IDENTIFIER_OF_PERSON = "identifier_of_person"
    IDENTIFIER_OF_CONTACT = "identifier_of_contact"
    PROFILE_IDENTIFIER_OF_CONTACT = "profile_identifier_of_contact"
    NAME_OF_CONTACT = "name_of_contact"
    NAME_TOO_CLOSE = "name_too_close"
    LOGO_UPLOADED = "logo_uploaded"
    LOGO_TYPE = "logo_type"
    LOGO_UPLOAD_TYPE = "logo_upload_type"
    TRAINING_NEEDS_EXAMPLES = "training_needs_examples"
    RULE_FOLLOWS_TYPE = "rule_follows_type"
    PERSONAL_SPACE_UNDELETABLE = "personal_space_undeletable"
    SPACE_NOT_EMPTY = "space_not_empty"
    SPACE_NAME_TAKEN = "space_name_taken"
    NO_WRITE_ACCESS_TO_SPACE = "no_write_access_to_space"
    USERNAME_TAKEN = "username_taken"
    LAST_ADMIN = "last_admin"
    USER_DELETION_BLOCKED = "user_deletion_blocked"
    DISPLAY_NAME_TAKEN = "display_name_taken"
    USERNAME_OF_OTHER = "username_of_other"
    LENSES_LIMIT = "lenses_limit"
    WEBHOOKS_LIMIT = "webhooks_limit"
    OPEN_FIELDS = "open_fields"
    DUPLICATE_OF = "duplicate_of"
    DUPLICATE_UNSEEN = "duplicate_unseen"
    NO_TEXT_YET = "no_text_yet"
    NO_STRUCTURE_YET = "no_structure_yet"
    BEING_PROCESSED = "being_processed"
    ONLY_FAILED_RETRIED = "only_failed_retried"
    RECEIVE_NOT_REPEATABLE = "receive_not_repeatable"
    NOT_WAITING_FOR_CONFIRMATION = "not_waiting_for_confirmation"
    STILL_RUNNING = "still_running"
    NO_TEXT_TO_EXTRACT = "no_text_to_extract"
    NO_VISION_MODEL = "no_vision_model"
    CANNOT_SKIP = "cannot_skip"
    UNCERTAIN_BEFORE_FILING = "uncertain_before_filing"
    INVALID_CREDENTIALS = "invalid_credentials"
    INVALID_ONE_TIME_CODE = "invalid_one_time_code"
    SECOND_FACTOR_REQUIRED = "second_factor_required"
    ACCOUNT_INACTIVE = "account_inactive"
    AUTHENTICATION_REQUIRED = "authentication_required"
    SESSION_EXPIRED = "session_expired"
    TOKEN_INVALID = "token_invalid"
    WRONG_PASSWORD = "wrong_password"
    TOTP_ALREADY_ON = "totp_already_on"
    NO_TOTP_SETUP = "no_totp_setup"
    TOTP_OFF = "totp_off"
    CODE_INVALID = "code_invalid"
    READ_ONLY_TOKEN = "read_only_token"
    CSRF_MISSING = "csrf_missing"
    SESSION_NEEDED = "session_needed"
    OIDC_MISMATCH = "oidc_mismatch"
    OIDC_RELINK = "oidc_relink"
    OIDC_LINKED_ELSEWHERE = "oidc_linked_elsewhere"
    OIDC_NO_ACCOUNT = "oidc_no_account"
    OIDC_PASSWORD_FIRST = "oidc_password_first"
    # the rest of the problems, rules disabled and skipped
    NOT_FOUND = "not_found"
    PAGE_NOT_FOUND = "page_not_found"
    FILE_NOT_FOUND = "file_not_found"
    RULE_VERSION_NOT_FOUND = "rule_version_not_found"
    NAME_EMPTY = "name_empty"
    NAME_TOO_LONG = "name_too_long"
    ADMINS_ONLY = "admins_only"
    EDITORS_ONLY = "editors_only"
    ADMINS_CANNOT = "admins_cannot"
    NO_WRITE_ACCESS_TO_DOCUMENT = "no_write_access_to_document"
    SESSION_NEEDED_CREATE_USER = "session_needed_create_user"
    SESSION_NEEDED_ROLE = "session_needed_role"
    SESSION_NEEDED_PROFILE = "session_needed_profile"
    PROFILE_OWN_ONLY = "profile_own_only"
    PERSONAL_SPACE_DESCRIBE = "personal_space_describe"
    SPACE_MANAGE = "space_manage"
    SPACE_MEMBERS_PERSONAL = "space_members_personal"
    SPACE_MEMBERS = "space_members"
    SPACE_RULE_APPLY = "space_rule_apply"
    RULE_DISABLED_DELETED = "rule_disabled_deleted"
    RULE_DISABLED_PERSONAL_SPACE = "rule_disabled_personal_space"
    RULE_DISABLED_CHOICE = "rule_disabled_choice"
    SKIP_CHANGED_MEANWHILE = "skip_changed_meanwhile"
    SKIP_NOT_AVAILABLE = "skip_not_available"
    # value checks a person meets in the UI
    NOT_IBAN = "not_iban"
    NOT_VAT_ID = "not_vat_id"
    NOT_CUSTOMER_NUMBER = "not_customer_number"
    NOT_PERSONNEL_NUMBER = "not_personnel_number"
    NOT_DOMAIN = "not_domain"
    FREE_MAIL_DOMAIN = "free_mail_domain"
    NOT_TAX_ID = "not_tax_id"
    NOT_SOCIAL_SECURITY_NUMBER = "not_social_security_number"
    NOT_HEALTH_INSURANCE_NUMBER = "not_health_insurance_number"
    NOT_EMAIL_ADDRESS = "not_email_address"
    BIRTH_DATE_TOO_EARLY = "birth_date_too_early"
    BIRTH_DATE_IN_FUTURE = "birth_date_in_future"
    ALIAS_TWICE = "alias_twice"
    PERSON_TOO_MANY_ALIASES = "person_too_many_aliases"
    PERSON_TOO_MANY_IDENTIFIERS = "person_too_many_identifiers"
    DISPLAY_NAME_IS_ALIAS = "display_name_is_alias"
    TOO_MANY_GROUPS = "too_many_groups"
    TOO_MANY_TOPICS = "too_many_topics"
    IDENTIFIER_TOPIC_NOT_ENABLED = "identifier_topic_not_enabled"
    ALIAS_IS_NAME = "alias_is_name"
    CONTACT_TOO_MANY_ALIASES = "contact_too_many_aliases"
    CONTACT_TOO_MANY_IDENTIFIERS = "contact_too_many_identifiers"
    ONLY_NUMBERS_NAME_USERS = "only_numbers_name_users"
    IDENTIFIER_TAKEN = "identifier_taken"
    TITLE_PATTERN_TOO_LONG = "title_pattern_too_long"
    DESCRIPTION_TOO_LONG = "description_too_long"
    TITLE_PATTERN_UNKNOWN = "title_pattern_unknown"
    TAG_OWN_PARENT = "tag_own_parent"
    GROUPS_MANUAL = "groups_manual"
    TAG_WRONG_SCOPE = "tag_wrong_scope"
    TAG_PARENT_OTHER_SCOPE = "tag_parent_other_scope"
    TAG_UNDER_OWN_CHILD = "tag_under_own_child"
    TAG_TOO_DEEP = "tag_too_deep"
    FIELD_GLOBAL_REQUIRED = "field_global_required"
    FIELD_TYPED_REQUIRED = "field_typed_required"
    FIELD_REQUIRED_OWN_TYPES = "field_required_own_types"
    CHOICE_NEEDS_CHOICES = "choice_needs_choices"
    CHOICES_NOT_UNIQUE = "choices_not_unique"
    ONLY_CHOICE_FIELDS_CHOICES = "only_choice_fields_choices"
    FIELD_NEEDS_TYPE = "field_needs_type"
    FIELD_IS_GLOBAL = "field_is_global"
    FIELD_ONLY_THIS_TYPE = "field_only_this_type"
    FIELD_NOT_FOR_TYPE = "field_not_for_type"
    NOT_A_URL = "not_a_url"
    URL_NOT_HTTP = "url_not_http"
    RECEIPT_IN_FUTURE = "receipt_in_future"
    PERSONAL_SPACE_NAME = "personal_space_name"
    PERSONAL_SPACE_EDITOR = "personal_space_editor"
    SPACE_NEEDS_EDITOR = "space_needs_editor"
    PASSWORD_TOO_SHORT = "password_too_short"
    PASSWORD_TOO_LONG = "password_too_long"
    PASSWORD_IS_USERNAME = "password_is_username"
    EXPIRY_IN_PAST = "expiry_in_past"
    URL_LENGTH = "url_length"
    URL_SPACES = "url_spaces"
    URL_INVALID = "url_invalid"
    URL_SCHEME = "url_scheme"
    URL_NO_HOST = "url_no_host"
    URL_CREDENTIALS = "url_credentials"
    URL_FRAGMENT = "url_fragment"
    HEADER_NAME_INVALID = "header_name_invalid"
    HEADER_RESERVED = "header_reserved"
    HEADER_VALUE_INVALID = "header_value_invalid"
    HEADER_TWICE = "header_twice"
    HEADERS_LIMIT = "headers_limit"
    HEADER_VALUE_MISSING = "header_value_missing"
    ICON_INVALID = "icon_invalid"
    COLOUR_INVALID = "colour_invalid"
    CARD_FIELD_UNKNOWN = "card_field_unknown"
    DUE_FIELD_NOT_DATE = "due_field_not_date"
    SORT_FIELD_INVALID = "sort_field_invalid"
    PATTERN_INVALID = "pattern_invalid"
    # how a search searched
    SEARCH_NO_EMBEDDINGS = "search_no_embeddings"
    SEARCH_EMBED_TIMEOUT = "search_embed_timeout"
    SEARCH_EMBED_FAILED = "search_embed_failed"
    SEARCH_EMBED_DIMENSIONS = "search_embed_dimensions"
    SEARCH_INDEX_UNAVAILABLE = "search_index_unavailable"
    SEARCH_NOT_CONFIGURED = "search_not_configured"


TEMPLATES: Mapping[ReasonCode, str] = {
    ReasonCode.TEXT: "{text}",
    ReasonCode.ERROR: "{detail}",
    ReasonCode.SIGNALS_DISAGREE: "the signals disagree: {names:or}",
    ReasonCode.ONLY_SUGGESTED: "'{name}' is only suggested: no signal is sure of it",
    ReasonCode.ONE_SIGNAL_ONLY: "only one signal names '{name}'",
    ReasonCode.ONLY_IDENTIFIER: "only an identifier points to '{name}'",
    ReasonCode.CONTACT_IS_RECIPIENT: "'{contact}' is the recipient, not the sender",
    ReasonCode.CONTACT_IDENTIFIERS_SEVERAL: "identifiers of several contacts stand in the text",
    ReasonCode.CONTACT_NEW_PROPOSED: "no contact matches '{sender}'; a new contact is proposed",
    ReasonCode.CONTACT_NONE: "no contact recognised",
    ReasonCode.CONTACT_NONE_NO_MODEL: "no contact recognised (the language model did not answer)",
    ReasonCode.CONTACT_NOT_IN_TEXT: "the contact '{contact}' does not appear in the text",
    ReasonCode.SENDER_NOT_A_CONTACT: (
        "'{sender}' is no contact, and only other signals point to '{contact}'"
    ),
    ReasonCode.SENDER_MATCHES_SEVERAL: "'{sender}' matches several contacts",
    ReasonCode.SENDER_ONLY_SIMILAR: "'{sender}' is only similar to the contact '{contact}'",
    ReasonCode.TYPE_NEW_PROPOSED: "no document type fits; a new type '{type}' is proposed",
    ReasonCode.TYPE_NONE: "no document type recognised",
    ReasonCode.TOPIC_WITHOUT_CONTACT: "no contact: a topic is one of a contact's",
    ReasonCode.TOPIC_NONE: "no topic of '{contact}' recognised",
    ReasonCode.TOPIC_CONTACT_SUGGESTED: "the contact '{contact}' is only suggested",
    ReasonCode.SPACE_CHOSEN_BY_PERSON: "a person chose the space",
    ReasonCode.SPACE_NAMED_UNSEEN: "names someone who would not see it there",
    ReasonCode.SPACE_STAYS_FOR_NAMED: (
        "stays: the space the signals name leaves out someone it names"
    ),
    ReasonCode.SPACE_SHOWS_MORE: "suggests another space, which shows it to more people",
    ReasonCode.SPACE_HAND_OVER: "suggests handing it over into another user's personal space",
    ReasonCode.SPACE_UPLOADER_UNSEEN: "suggests a space its uploader does not see",
    ReasonCode.SPACE_OTHER: "suggests another space",
    ReasonCode.SPACES_DISAGREE: "the signals name different spaces",
    ReasonCode.DATE_NONE: "no date recognised",
    ReasonCode.DATE_NONE_FROM_MODEL: (
        "no date recognised: the language model gave none ({why:reason})"
    ),
    ReasonCode.NOT_A_DATE: "'{value}' is not a date",
    ReasonCode.DATE_IMPLAUSIBLE: "{date:date} is not plausible",
    ReasonCode.SAME_AS_DOCUMENT_DATE: "the same date as the document date",
    ReasonCode.NOT_A_PERIOD: "'{value}' is not a period",
    ReasonCode.PERIOD_IMPLAUSIBLE: "{period} is not plausible",
    ReasonCode.PERIOD_NO_YEAR: "no year given; the year of the document date is assumed",
    ReasonCode.SAME_DAY_AS_DOCUMENT_DATE: "the same day as the document date",
    ReasonCode.FIELD_SET_BY_HAND: "'{field}' is set by hand",
    ReasonCode.FIELD_BY_HAND_MISSING: "'{field}' is set by hand and has no value yet",
    ReasonCode.FIELD_NOT_FOUND: "'{field}' was not found",
    ReasonCode.FIELD_NOT_READ_NO_MODEL: "'{field}' was not read: no language model is configured",
    ReasonCode.VALUE_INVALID: "'{value}' is not a valid value of '{field}' ({type})",
    ReasonCode.QUOTE_NOT_IN_TEXT: "the quoted passage does not appear in the text",
    ReasonCode.QUOTE_MISSING: "no quoted passage",
    ReasonCode.QUOTE_WITHOUT_VALUE: "the quoted passage does not show the value",
    ReasonCode.QUOTE_TOO_SHORT: "the quoted passage is too short to show the value",
    ReasonCode.DATE_NOT_IN_TEXT: "the date does not appear in the text",
    ReasonCode.PERIOD_NOT_IN_TEXT: "the period does not appear in the text",
    ReasonCode.AMOUNT_NOT_IN_TEXT: "the amount does not appear in the text",
    ReasonCode.CURRENCY_NOT_IN_TEXT: "the currency {currency} does not appear in the text",
    ReasonCode.NUMBER_NOT_IN_TEXT: "the number does not appear in the text",
    ReasonCode.LINK_NOT_IN_TEXT: "the link does not appear in the text",
    ReasonCode.TEXT_NOT_IN_TEXT: "the text does not appear in the text",
    ReasonCode.VALUE_READ_UNSURE: "the value was read unsure ({unsure:number}%)",
    ReasonCode.PAGE_POORLY_READ: (
        "page {page:number} was poorly read ({share:percent} of its words unsure)"
    ),
    ReasonCode.PAGE_POORLY_READ_CONTENT: (
        "page {page:number} was poorly read ({share:percent} of its content words unsure)"
    ),
    ReasonCode.SURROUNDINGS_POORLY_READ: (
        "the text around the value was poorly read ({unsure:number} of {words:number} content "
        "words unsure)"
    ),
    ReasonCode.SOURCE_LACKS_CONTACT: "no contact in the source system",
    ReasonCode.SOURCE_LACKS_DOCUMENT_TYPE: "no document type in the source system",
    ReasonCode.SOURCE_LACKS_DOCUMENT_DATE: "no document date in the source system",
    ReasonCode.PAPERLESS_USER_REVIEW: "Paperless user '{name}': to be checked in Lekto",
    ReasonCode.PAPERLESS_CORRESPONDENT_REVIEW: (
        "Paperless correspondent '{name}': to be checked in Lekto"
    ),
    ReasonCode.PAPERLESS_DOCUMENT_TYPE_REVIEW: (
        "Paperless document type '{name}': to be checked in Lekto"
    ),
    ReasonCode.PAPERLESS_TAG_REVIEW: "Paperless tag '{name}': to be checked in Lekto",
    ReasonCode.PAPERLESS_CUSTOM_FIELD_REVIEW: (
        "Paperless custom field '{name}': to be checked in Lekto"
    ),
    ReasonCode.PAPERLESS_STORAGE_PATH_REVIEW: (
        "Paperless storage path '{name}': to be checked in Lekto"
    ),
    ReasonCode.PAPERLESS_ASN_REVIEW: (
        "Paperless archive serial number '{name}': to be checked in Lekto"
    ),
    ReasonCode.FIELD_DOES_NOT_APPLY: "'{field}' does not apply",
    ReasonCode.FIELD_GONE: "the field no longer exists",
    ReasonCode.CONTACT_GONE: "contact {id} no longer exists",
    ReasonCode.DOCUMENT_TYPE_GONE: "document_type {id} no longer exists",
    ReasonCode.TOPIC_GONE: "topic {id} no longer exists",
    ReasonCode.TAG_GONE: "tag {id} no longer exists",
    ReasonCode.SPACE_GONE: "space {id} no longer exists",
    ReasonCode.TAG_IS_GROUP: "tag '{tag}' is a group, not a document tag",
    ReasonCode.RULE_OTHER_SPACE: "the rule belongs to another space",
    ReasonCode.SPACE_NO_RIGHT_ANY_MORE: "no right to file into space '{space}' (any more)",
    ReasonCode.SPACE_NO_RIGHT: "you have no right to file into space '{space}'",
    ReasonCode.SPACE_WIDENS_UNCONFIRMED: (
        "files into the space '{space}', which more people see, with an unconfirmed "
        "{fields:fields}; not accepted"
    ),
    ReasonCode.SPACE_WIDENS_NEEDS_CONFIRMED: (
        "files into the space '{space}', which more people see, only with a confirmed "
        "{fields:fields}"
    ),
    ReasonCode.REVIEW_ON_ARRIVAL_ONLY: "reviews are forced on arrival only",
    ReasonCode.REVIEW_CONFIRMED: "a person confirmed the review",
    ReasonCode.RULES_DISAGREE: "rules set different values ({values:rule_values})",
    ReasonCode.VALUE_OTHER_NOT_ACCEPTED: (
        "the document has another value ({value:value}); not accepted"
    ),
    ReasonCode.PERSON_DECIDED_FIELD: "a person decided this field",
    ReasonCode.RULE_VALUE_ON_UNCONFIRMED: (
        "a rule set another value on unconfirmed values ({value:value})"
    ),
    ReasonCode.MODEL_VALUE_OTHER: "the model set another value ({value:value})",
    ReasonCode.RULES_VALUE_ON_UNCONFIRMED: (
        "rules: a rule set another value on unconfirmed values ({value:value})"
    ),
    ReasonCode.RULES_MODEL_VALUE_OTHER: "rules: the model set another value ({value:value})",
    ReasonCode.TOPIC_PERSON_CHOSE: "a person chose the topic '{topic}', which it does not enable",
    ReasonCode.TOPIC_NO_CONTACT: "the document has no contact",
    ReasonCode.TOPIC_NOT_ENABLED: "its contact does not enable the topic '{topic}'",
    ReasonCode.TAG_ADDED_AND_REMOVED: "tag '{tag}' is added and removed by rules",
    ReasonCode.TAG_REMOVED_BY_PERSON: "a person removed tag '{tag}'",
    ReasonCode.TAG_SET_BY_PERSON: "a person set tag '{tag}'",
    ReasonCode.TAG_ABOVE_KEPT: "tag '{tag}' is above a tag the document has",
    ReasonCode.TITLE_EMPTY: "the title would be empty",
    ReasonCode.TITLE_YIELDS: "another rule sets the title",
    ReasonCode.VALUE_EMPTY: "the value would be empty",
    ReasonCode.TEMPLATE_MISSING_VALUE: "{path} has no value",
    ReasonCode.NODE_ATTEMPTS_EXHAUSTED: (
        "node did not finish in {attempts:number} attempts (the worker died or ran out of time "
        "each time)"
    ),
    ReasonCode.NODE_CRASHED: "{error}: {detail}",
    ReasonCode.FILE_NOT_PDF_OR_IMAGE: "the file is no PDF and no image",
    ReasonCode.FILE_DAMAGED: "the file is damaged or not a valid document",
    ReasonCode.FILE_NOT_PROCESSABLE: "the file cannot be processed",
    ReasonCode.PDF_ENCRYPTED: "the PDF is encrypted",
    ReasonCode.PDF_UNREADABLE: "the PDF cannot be read",
    ReasonCode.PDF_UNREADABLE_DETAIL: "the PDF cannot be read: {detail}",
    ReasonCode.IMAGE_UNREADABLE: "the image cannot be read",
    ReasonCode.IMAGE_UNREADABLE_DETAIL: "the image cannot be read: {detail}",
    ReasonCode.DOCUMENT_NO_PAGES: "the document has no pages",
    ReasonCode.OCR_FAILED: "{problem:reason}: {detail}",
    ReasonCode.TEXT_UNREADABLE: (
        "the text in the PDF cannot be read (a font without a character map); every page was "
        "recognised from its image"
    ),
    ReasonCode.SIGNATURE_DROPPED: (
        "the original is digitally signed; the archive does not carry the signature (the "
        "original is unchanged)"
    ),
    ReasonCode.COLOURS_CONVERTED: (
        "the colours were converted to RGB to make the archive PDF/A (the original is unchanged)"
    ),
    ReasonCode.NOT_PDFA: "not PDF/A: {detail}",
    ReasonCode.ARCHIVE_NOT_PDFA: "the archive could not be made PDF/A",
    ReasonCode.VISION_READ: (
        "every page was read by the vision language model {model} ({endpoint})"
    ),
    ReasonCode.VISION_NOT_CONFIGURED: (
        "a person asked for the vision language model, but none is configured"
    ),
    ReasonCode.NO_TEXT: "no text recognised: the pages are blank or hold only pictures",
    ReasonCode.ANSWER_UNFIT: "the model's answer does not fit the schema: {detail}",
    ReasonCode.NOTHING_RECOGNISED: "nothing recognised: no contact, document type or date",
    ReasonCode.MASTER_DATA_CHANGED: (
        "the master data changed during the node; nothing was applied ({detail})"
    ),
    ReasonCode.METADATA_UNFIT: "the metadata of the source system no longer fits: {detail}",
    ReasonCode.TAKEN_OVER: "taken over from the source system",
    ReasonCode.SPACE_CHANGED_MEANWHILE: ("the space the signals chose changed meanwhile; it stays"),
    ReasonCode.RULES_BACK_AND_FORTH: "rules move it back and forth: {spaces:path}",
    ReasonCode.RULES_CHANGE_UNFIT: "the rules' change does not fit: {detail}",
    ReasonCode.SIGNAL_DID_NOT_RUN: "it did not run",
    ReasonCode.NO_LANGUAGE_MODEL: "no language model is configured",
    ReasonCode.NO_DOCUMENT_TEXT: "the document has no text",
    ReasonCode.NO_CLASSIFIER: "no classifier is configured",
    ReasonCode.CLASSIFIER_UNUSABLE: "the classifier cannot be used: {detail}",
    ReasonCode.CLASSIFIER_UNTRAINED: "no model is trained yet",
    ReasonCode.NEIGHBOURS_OFF: "neighbours are turned off",
    ReasonCode.NO_EMBEDDING_INDEX: "there is no search index with embeddings",
    ReasonCode.TEXT_NOT_EMBEDDED: "the text could not be embedded: {detail}",
    ReasonCode.VECTOR_MISFIT: "the text's vector does not fit the index",
    ReasonCode.NO_UPLOADER: "the document has no active uploader to look from",
    ReasonCode.INDEX_UNAVAILABLE: "the search index cannot be asked: {detail}",
    ReasonCode.NO_SIMILAR: "no similar confirmed document",
    ReasonCode.INPUT_MISSING: "a value is required",
    ReasonCode.INPUT_TOO_SHORT: "at least {min:number} characters",
    ReasonCode.INPUT_TOO_LONG: "at most {max:number} characters",
    ReasonCode.INPUT_TOO_FEW: "at least {min:number} entries",
    ReasonCode.INPUT_TOO_MANY: "at most {max:number} entries",
    ReasonCode.INPUT_TOO_SMALL: "at least {min:number}",
    ReasonCode.INPUT_ABOVE: "more than {min:number}",
    ReasonCode.INPUT_TOO_LARGE: "at most {max:number}",
    ReasonCode.INPUT_BELOW: "less than {max:number}",
    ReasonCode.INPUT_CHOICE: "not one of the allowed values",
    ReasonCode.INPUT_NOT_ID: "not a valid id",
    ReasonCode.INPUT_NOT_DATE: "not a valid date",
    ReasonCode.INPUT_NOT_DATETIME: "not a valid time",
    ReasonCode.INPUT_NOT_NUMBER: "not a number",
    ReasonCode.INPUT_NOT_INTEGER: "not a whole number",
    ReasonCode.INPUT_NOT_BOOLEAN: "not yes or no",
    ReasonCode.INPUT_NOT_TEXT: "not a text",
    ReasonCode.INPUT_NOT_LIST: "not a list",
    ReasonCode.INPUT_NOT_OBJECT: "not an object",
    ReasonCode.INPUT_UNKNOWN: "not allowed here",
    ReasonCode.INPUT_PATTERN: "not in the expected form",
    ReasonCode.INPUT_INVALID: "{detail}",
    ReasonCode.IN_USE: "'{name}' is in use",
    ReasonCode.NAME_TAKEN: "'{name}' already exists",
    ReasonCode.TOPIC_CARRIED: (
        "documents of '{contact}' carry the topic '{topic}': give them another topic first"
    ),
    ReasonCode.CHOICES_IN_USE: "documents use the choices {choices:list}",
    ReasonCode.VALUES_OUTSIDE_SCOPE: "documents outside the new scope have values",
    ReasonCode.TITLE_PATTERN_USES_FIELD: "the title pattern of '{type}' uses field.{key}",
    ReasonCode.TYPE_HAS_VALUES: "documents of '{type}' have values for '{field}'",
    ReasonCode.TAG_HAS_CHILDREN: "'{tag}' has tags below it",
    ReasonCode.TAG_HAS_CONTACTS: "contacts are in '{tag}'",
    ReasonCode.TAG_HAS_TYPES: "document types are in '{tag}'",
    ReasonCode.TOPIC_ENABLED_BY: "the contacts {contacts:list} enable '{tag}'",
    ReasonCode.TAG_USED_BY_RULES: "'{tag}' is used by the rules {rules:list}",
    ReasonCode.FIELD_USED_BY_PATTERNS: "field.{key} is used by the title patterns of {types:list}",
    ReasonCode.FIELD_USED_BY_RULES: (
        "field.{key} is used by the templates of the rules {rules:list}"
    ),
    ReasonCode.FIELD_KEY_TAKEN: "'{field}' would be field.{key} in templates, as '{other}' is",
    ReasonCode.IDENTIFIER_OF_PERSON: "'{value}' is an identifier of a person",
    ReasonCode.IDENTIFIER_OF_CONTACT: (
        "'{value}' is already an identifier of the contact '{contact}'"
    ),
    ReasonCode.PROFILE_IDENTIFIER_OF_CONTACT: (
        "'{value}' is an identifier of the contact '{contact}'"
    ),
    ReasonCode.NAME_OF_CONTACT: "'{name}' is already a name of the contact '{contact}'",
    ReasonCode.NAME_TOO_CLOSE: "'{name}' is too close to '{other}' of the contact '{contact}'",
    ReasonCode.LOGO_UPLOADED: "'{contact}' has an uploaded logo; a fetched one never replaces it",
    ReasonCode.LOGO_TYPE: "a logo is a PNG, JPEG, WebP or ICO image",
    ReasonCode.LOGO_UPLOAD_TYPE: "a logo is a PNG, JPEG or WebP image",
    ReasonCode.TRAINING_NEEDS_EXAMPLES: (
        "{confirmed:number} confirmed documents or decided spaces; training needs {needed:number}"
    ),
    ReasonCode.RULE_FOLLOWS_TYPE: (
        "the rule of the title pattern of '{type}' follows the document type: change the pattern "
        "there"
    ),
    ReasonCode.PERSONAL_SPACE_UNDELETABLE: "a personal space cannot be deleted",
    ReasonCode.SPACE_NOT_EMPTY: "space '{space}' is not empty",
    ReasonCode.SPACE_NAME_TAKEN: "space '{space}' already exists",
    ReasonCode.NO_WRITE_ACCESS_TO_SPACE: "no write access to space '{space}'",
    ReasonCode.USERNAME_TAKEN: "username '{username}' is taken",
    ReasonCode.LAST_ADMIN: "the last active admin must stay an active admin",
    ReasonCode.USER_DELETION_BLOCKED: (
        "deleting the user needs a decision on these spaces: {spaces:list}"
    ),
    ReasonCode.DISPLAY_NAME_TAKEN: "'{name}' is the name of another user",
    ReasonCode.USERNAME_OF_OTHER: "username '{username}' is another user's name",
    ReasonCode.LENSES_LIMIT: "at most {max:number} lenses per user",
    ReasonCode.WEBHOOKS_LIMIT: "at most {max:number} webhooks per user",
    ReasonCode.OPEN_FIELDS: "decide the open fields first: {fields:fields}",
    ReasonCode.DUPLICATE_OF: "duplicate of document {id}",
    ReasonCode.DUPLICATE_UNSEEN: "the file lies in Lekto already, in a space you cannot see",
    ReasonCode.NO_TEXT_YET: "document has no text yet",
    ReasonCode.NO_STRUCTURE_YET: "document has no structure yet",
    ReasonCode.BEING_PROCESSED: "document {id} is being processed",
    ReasonCode.ONLY_FAILED_RETRIED: "document {id}: only failed processing is retried",
    ReasonCode.RECEIVE_NOT_REPEATABLE: "the receive node cannot be repeated",
    ReasonCode.NOT_WAITING_FOR_CONFIRMATION: "document {id} is not waiting for confirmation",
    ReasonCode.STILL_RUNNING: "document {id}: {nodes:nodes} is still running; confirm afterwards",
    ReasonCode.NO_TEXT_TO_EXTRACT: "document {id} has no text to extract from",
    ReasonCode.NO_VISION_MODEL: "no vision language model is configured",
    ReasonCode.CANNOT_SKIP: "processing stopped at {nodes:nodes}; cannot skip it",
    ReasonCode.UNCERTAIN_BEFORE_FILING: (
        "document {id} has uncertain results; confirm them before filing"
    ),
    ReasonCode.INVALID_CREDENTIALS: "invalid username or password",
    ReasonCode.INVALID_ONE_TIME_CODE: "invalid one-time code",
    ReasonCode.SECOND_FACTOR_REQUIRED: "a one-time code is required",
    ReasonCode.ACCOUNT_INACTIVE: "the account is not active",
    ReasonCode.AUTHENTICATION_REQUIRED: "authentication is required",
    ReasonCode.SESSION_EXPIRED: "the session has expired",
    ReasonCode.TOKEN_INVALID: "the token is invalid or has expired",
    ReasonCode.WRONG_PASSWORD: "the current password is wrong",
    ReasonCode.TOTP_ALREADY_ON: "TOTP is already on; turn it off first",
    ReasonCode.NO_TOTP_SETUP: "no TOTP setup to confirm",
    ReasonCode.TOTP_OFF: "TOTP is off",
    ReasonCode.CODE_INVALID: "the code is not valid",
    ReasonCode.READ_ONLY_TOKEN: "this API token may only read",
    ReasonCode.CSRF_MISSING: "the header {header} is missing or wrong",
    ReasonCode.SESSION_NEEDED: "this needs a signed-in session, not an API token",
    ReasonCode.OIDC_MISMATCH: "the sign-in does not match the one started here",
    ReasonCode.OIDC_RELINK: "sign in again to link the account",
    ReasonCode.OIDC_LINKED_ELSEWHERE: "this account is linked to another user",
    ReasonCode.OIDC_NO_ACCOUNT: "no account here is linked to this sign-in",
    ReasonCode.OIDC_PASSWORD_FIRST: "set a password first; without it you could not sign in",
    ReasonCode.NOT_FOUND: "{kind:thing} {id} not found",
    ReasonCode.PAGE_NOT_FOUND: "page {page:number} of document {id} not found",
    ReasonCode.FILE_NOT_FOUND: "{file:thing} of document {id} not found",
    ReasonCode.RULE_VERSION_NOT_FOUND: "version {number:number} of rule {id} not found",
    ReasonCode.NAME_EMPTY: "{what:thing} must not be empty",
    ReasonCode.NAME_TOO_LONG: "{what:thing} must have at most {max:number} characters",
    ReasonCode.ADMINS_ONLY: "only admins {action:action}",
    ReasonCode.EDITORS_ONLY: "only editors and admins {action:action}",
    ReasonCode.ADMINS_CANNOT: "admins cannot {action:action}",
    ReasonCode.NO_WRITE_ACCESS_TO_DOCUMENT: "no write access to document {id}",
    ReasonCode.SESSION_NEEDED_CREATE_USER: (
        "this needs a signed-in session: an API token can only create users with the role "
        "'user' and no password"
    ),
    ReasonCode.SESSION_NEEDED_ROLE: (
        "this needs a signed-in session: an API token cannot change a role or the state of an admin"
    ),
    ReasonCode.SESSION_NEEDED_PROFILE: (
        "this needs a signed-in session: an API token sets only the display name and the "
        "e-mail address"
    ),
    ReasonCode.PROFILE_OWN_ONLY: "only the user and admins see and change a profile",
    ReasonCode.PERSONAL_SPACE_DESCRIBE: "only its user and admins describe the personal space {id}",
    ReasonCode.SPACE_MANAGE: "only editors and admins manage space {id}",
    ReasonCode.SPACE_MEMBERS_PERSONAL: "only its user and admins choose the members of space {id}",
    ReasonCode.SPACE_MEMBERS: "only editors and admins choose the members of space {id}",
    ReasonCode.SPACE_RULE_APPLY: "only the space's editors and admins apply a space rule",
    ReasonCode.RULE_DISABLED_DELETED: "{kind:thing} '{name}' was deleted",
    ReasonCode.RULE_DISABLED_PERSONAL_SPACE: "the personal space of '{user}' was deleted",
    ReasonCode.RULE_DISABLED_CHOICE: "field '{field}' no longer allows a value the rule uses",
    ReasonCode.SKIP_CHANGED_MEANWHILE: "changed meanwhile; not applied",
    ReasonCode.SKIP_NOT_AVAILABLE: "not available",
    ReasonCode.NOT_IBAN: "'{value}' is not a valid IBAN",
    ReasonCode.NOT_VAT_ID: "'{value}' is not a VAT number",
    ReasonCode.NOT_CUSTOMER_NUMBER: (
        "'{value}' is no customer number (4 to 30 letters and digits, one a digit)"
    ),
    ReasonCode.NOT_PERSONNEL_NUMBER: (
        "'{value}' is no personnel number (3 to 30 letters and digits, one a digit)"
    ),
    ReasonCode.NOT_DOMAIN: "'{value}' is not a domain",
    ReasonCode.FREE_MAIL_DOMAIN: "'{value}' is a free mail provider, not one contact's",
    ReasonCode.NOT_TAX_ID: "'{value}' is not a valid tax ID (11 digits, check digit)",
    ReasonCode.NOT_SOCIAL_SECURITY_NUMBER: (
        "'{value}' is not a valid social security number (12 characters, check digit)"
    ),
    ReasonCode.NOT_HEALTH_INSURANCE_NUMBER: (
        "'{value}' is not a valid health insurance number (a letter, 9 digits)"
    ),
    ReasonCode.NOT_EMAIL_ADDRESS: "'{value}' is not an e-mail address",
    ReasonCode.BIRTH_DATE_TOO_EARLY: "a birth date before {date:date}",
    ReasonCode.BIRTH_DATE_IN_FUTURE: "a birth date in the future",
    ReasonCode.ALIAS_TWICE: "the alias '{alias}' is given twice",
    ReasonCode.PERSON_TOO_MANY_ALIASES: "at most {max:number} aliases",
    ReasonCode.PERSON_TOO_MANY_IDENTIFIERS: "at most {max:number} identifiers",
    ReasonCode.DISPLAY_NAME_IS_ALIAS: "'{name}' is the display name and an alias",
    ReasonCode.TOO_MANY_GROUPS: "at most {max:number} groups",
    ReasonCode.TOO_MANY_TOPICS: "a contact enables at most {max:number} topics",
    ReasonCode.IDENTIFIER_TOPIC_NOT_ENABLED: (
        "the topic of the identifier '{value}' is none the contact enables"
    ),
    ReasonCode.ALIAS_IS_NAME: "the alias '{alias}' is the contact's name",
    ReasonCode.CONTACT_TOO_MANY_ALIASES: "a contact has at most {max:number} aliases",
    ReasonCode.CONTACT_TOO_MANY_IDENTIFIERS: "a contact has at most {max:number} identifiers",
    ReasonCode.ONLY_NUMBERS_NAME_USERS: (
        "only a customer or personnel number names the user it belongs to"
    ),
    ReasonCode.IDENTIFIER_TAKEN: "'{value}' is already taken",
    ReasonCode.TITLE_PATTERN_TOO_LONG: "a title pattern is at most {max:number} characters",
    ReasonCode.DESCRIPTION_TOO_LONG: "description must not be longer than {max:number} characters",
    ReasonCode.TITLE_PATTERN_UNKNOWN: (
        "the title pattern uses {value}, which a template of '{type}' does not know (fields: "
        "field.<key> of those that apply to the type)"
    ),
    ReasonCode.TAG_OWN_PARENT: "a tag cannot be its own parent",
    ReasonCode.GROUPS_MANUAL: "groups are set by hand only (assignment 'manual')",
    ReasonCode.TAG_WRONG_SCOPE: "'{tag}' is a {scope:thing}, not a {expected:thing}",
    ReasonCode.TAG_PARENT_OTHER_SCOPE: (
        "'{parent}' is a tag of another scope: a parent tag has the scope of its children"
    ),
    ReasonCode.TAG_UNDER_OWN_CHILD: "'{tag}' cannot go under '{parent}', which is below it",
    ReasonCode.TAG_TOO_DEEP: "tags are nested at most {max:number} levels deep",
    ReasonCode.FIELD_GLOBAL_REQUIRED: "a global field is required by `required`, not per type",
    ReasonCode.FIELD_TYPED_REQUIRED: "a typed field is required per type",
    ReasonCode.FIELD_REQUIRED_OWN_TYPES: "a field can only be required for its own types",
    ReasonCode.CHOICE_NEEDS_CHOICES: "a choice field needs at least one choice",
    ReasonCode.CHOICES_NOT_UNIQUE: "choices must be unique",
    ReasonCode.ONLY_CHOICE_FIELDS_CHOICES: "only choice fields have choices",
    ReasonCode.FIELD_NEEDS_TYPE: "give at least one document type, or null for global",
    ReasonCode.FIELD_IS_GLOBAL: "'{field}' is global: it belongs to every type",
    ReasonCode.FIELD_ONLY_THIS_TYPE: (
        "'{field}' belongs to no other type: give it one or delete it in its own dialog"
    ),
    ReasonCode.FIELD_NOT_FOR_TYPE: "field '{field}' does not apply to this document type",
    ReasonCode.NOT_A_URL: "invalid URL '{value}'",
    ReasonCode.URL_NOT_HTTP: "URL must be absolute http(s), got '{value}'",
    ReasonCode.RECEIPT_IN_FUTURE: "created_at: not in the future",
    ReasonCode.PERSONAL_SPACE_NAME: "a personal space keeps its name",
    ReasonCode.PERSONAL_SPACE_EDITOR: "the user of a personal space always edits it",
    ReasonCode.SPACE_NEEDS_EDITOR: "a space keeps at least one editor",
    ReasonCode.PASSWORD_TOO_SHORT: "the password must have at least {min:number} characters",
    ReasonCode.PASSWORD_TOO_LONG: "the password must have at most {max:number} characters",
    ReasonCode.PASSWORD_IS_USERNAME: "the password must not be the username",
    ReasonCode.EXPIRY_IN_PAST: "the expiry must be in the future",
    ReasonCode.URL_LENGTH: "the URL must have 1 to {max:number} characters",
    ReasonCode.URL_SPACES: "the URL must not contain spaces or control characters",
    ReasonCode.URL_INVALID: "the URL is not valid",
    ReasonCode.URL_SCHEME: "the URL must start with http:// or https://",
    ReasonCode.URL_NO_HOST: "the URL needs a host",
    ReasonCode.URL_CREDENTIALS: "the URL must not contain a user name or password",
    ReasonCode.URL_FRAGMENT: "the URL must not have a fragment",
    ReasonCode.HEADER_NAME_INVALID: "'{name}' is no valid header name",
    ReasonCode.HEADER_RESERVED: "Lekto sets the header '{name}' itself",
    ReasonCode.HEADER_VALUE_INVALID: (
        "the value of '{name}' must have 1 to {max:number} printable ASCII characters, spaces "
        "only inside"
    ),
    ReasonCode.HEADER_TWICE: "the header '{name}' is given twice",
    ReasonCode.HEADERS_LIMIT: "at most {max:number} headers",
    ReasonCode.HEADER_VALUE_MISSING: "give a value for the new header '{name}'",
    ReasonCode.ICON_INVALID: (
        "'{icon}' is no icon name (lower-case letters, digits and hyphens, at most "
        "{max:number} characters)"
    ),
    ReasonCode.COLOUR_INVALID: "'{colour}' is no colour: one of the palette or #rrggbb",
    ReasonCode.CARD_FIELD_UNKNOWN: "card_field_ids: no field {id}",
    ReasonCode.DUE_FIELD_NOT_DATE: "due_field_id: not a date field",
    ReasonCode.SORT_FIELD_INVALID: (
        "sort_field_id: not a field a list sorts by (date, period, number or amount)"
    ),
    ReasonCode.PATTERN_INVALID: "invalid pattern '{pattern}': {detail}",
    ReasonCode.SEARCH_NO_EMBEDDINGS: "searched by words only: no embeddings are set up",
    ReasonCode.SEARCH_EMBED_TIMEOUT: (
        "searched by words only: the meaning of the query was not ready within "
        "{seconds:number} seconds"
    ),
    ReasonCode.SEARCH_EMBED_FAILED: (
        "searched by words only: the embedding service could not give the meaning of the query"
    ),
    ReasonCode.SEARCH_EMBED_DIMENSIONS: (
        "searched by words only: the query's vector has {got:number} numbers, the index "
        "{wanted:number}"
    ),
    ReasonCode.SEARCH_INDEX_UNAVAILABLE: (
        "the full-text search cannot be reached; the list and its filters work without it"
    ),
    ReasonCode.SEARCH_NOT_CONFIGURED: "this installation has no search index",
}


class Action(StrEnum):
    """What only some may do (`ADMINS_ONLY`, `EDITORS_ONLY`, `ADMINS_CANNOT`): the parameter
    of the kind `action`, written in English as `ACTIONS` has it."""

    MANAGE_USERS = "manage_users"
    CHANGE_MASTER_DATA = "change_master_data"
    SEE_ALL_INBOXES = "see_all_inboxes"
    COUNT_ALL_DOCUMENTS = "count_all_documents"
    LIST_ALL_DOCUMENTS = "list_all_documents"
    SEARCH_ALL_DOCUMENTS = "search_all_documents"
    LIST_ALL_RULES = "list_all_rules"
    LIST_ALL_SPACES = "list_all_spaces"
    TRAIN_CLASSIFIER = "train_classifier"
    SEE_CLASSIFIER = "see_classifier"
    REBUILD_INDEX = "rebuild_index"
    REPARSE_ALL = "reparse_all"
    MAKE_GLOBAL_RULES = "make_global_rules"
    CHANGE_GLOBAL_RULES = "change_global_rules"
    MAKE_SPACE_RULES = "make_space_rules"
    CHANGE_UNCONFIRMED = "change_unconfirmed"
    GIVE_UPLOAD_METADATA = "give_upload_metadata"
    UPLOAD_FOR_OTHERS = "upload_for_others"
    CONTROL_PROCESSING = "control_processing"
    READ_PROCESSING_LOG = "read_processing_log"
    READ_EXCHANGES = "read_exchanges"
    REVIEW_DOCUMENT = "review_document"
    MOVE_DOCUMENT = "move_document"
    DELETE_DOCUMENT = "delete_document"
    RESET_OWN_PASSWORD = "reset_own_password"
    TURN_OFF_OWN_TOTP = "turn_off_own_totp"


ACTIONS: Mapping[Action, str] = {
    Action.MANAGE_USERS: "manage users",
    Action.CHANGE_MASTER_DATA: "change master data",
    Action.SEE_ALL_INBOXES: "see the inboxes of all users",
    Action.COUNT_ALL_DOCUMENTS: "count the documents of all users",
    Action.LIST_ALL_DOCUMENTS: "list the documents of all users",
    Action.SEARCH_ALL_DOCUMENTS: "search the documents of all users",
    Action.LIST_ALL_RULES: "list the rules of all users",
    Action.LIST_ALL_SPACES: "list every user's spaces",
    Action.TRAIN_CLASSIFIER: "train the classifier",
    Action.SEE_CLASSIFIER: "see the classifier",
    Action.REBUILD_INDEX: "rebuild the search index",
    Action.REPARSE_ALL: "read the text of all documents again",
    Action.MAKE_GLOBAL_RULES: "make global rules",
    Action.CHANGE_GLOBAL_RULES: "change global rules",
    Action.MAKE_SPACE_RULES: "make the rules of this space",
    Action.CHANGE_UNCONFIRMED: "change a document without confirming it",
    Action.GIVE_UPLOAD_METADATA: "give metadata with an upload",
    Action.UPLOAD_FOR_OTHERS: "upload on behalf of another user",
    Action.CONTROL_PROCESSING: "control the processing of this document",
    Action.READ_PROCESSING_LOG: "read the processing log of this document",
    Action.READ_EXCHANGES: "read the model exchanges of this document",
    Action.REVIEW_DOCUMENT: "review this document",
    Action.MOVE_DOCUMENT: "move this document",
    Action.DELETE_DOCUMENT: "delete this document",
    Action.RESET_OWN_PASSWORD: "reset their own password here",
    Action.TURN_OFF_OWN_TOTP: "turn off their own TOTP here",
}


KINDS: Mapping[str, str] = {
    "": "text",
    "number": "number",
    "percent": "percent",
    "date": "date",
    "value": "value",
    "or": "names",
    "fields": "fields",
    "rule_values": "rule_values",
    "path": "path",
    "reason": "reason",
    "list": "list",
    "nodes": "nodes",
    "thing": "thing",
    "action": "action",
}
"""The kinds a template may give a parameter (after its colon; none: text), by the name the
catalog gives them: `number` a number, `percent` a fraction from 0 to 1, `date` a day in ISO
8601, `value` a field's value as a reason shows it (a string, true or false for yes or no, null
for none), `names` a list of names, `fields` a list of check fields (`contact`, `field:<id>`,
...), `rule_values` a list of `{"rule": name, "value": value}` (what each rule sets), `path`
a list of names one after the other (spaces a document went through), `reason` another reason
(`Reason.to_json`), `list` a list of names, quoted and joined by commas, `nodes` a list of
nodes of the pipeline (`ocr`, ...), `thing` what something is, as an English noun (`document
type`, `title`), `action` one of `Action` (what only some may do)."""


class _Formatter(string.Formatter):
    def format_field(self, value: object, format_spec: str) -> str:
        match format_spec:
            case "percent":
                return format(value, ".0%")
            case "value":
                return _value(value)
            case "or":
                return " or ".join(f"'{item}'" for item in _items(value))
            case "fields":
                return ", ".join(str(item) for item in _items(value))
            case "rule_values":
                return ", ".join(
                    f"'{item.get('rule')}': {_value(item.get('value'))}"
                    for item in _items(value)
                    if isinstance(item, dict)
                )
            case "path":
                return " → ".join(str(item) for item in _items(value))
            case "list":
                return ", ".join(f"'{item}'" for item in _items(value))
            case "nodes":
                return ", ".join(str(item) for item in _items(value))
            case "action":
                try:
                    return ACTIONS[Action(str(value))]
                except ValueError:
                    return str(value)
            case "reason":
                try:
                    return Reason.from_json(value).text  # type: ignore[arg-type]
                except ValidationError:
                    return str(value)
        return str(value)


def _items(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else [value]


def _value(value: object) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


_FORMATTER = _Formatter()


def _parameters(template: str) -> dict[str, str]:
    """The parameters of `template` with their kinds."""
    found: dict[str, str] = {}
    for _, name, spec, _ in _FORMATTER.parse(template):
        if name is not None:
            found[name] = KINDS[spec or ""]
    return found


PARAMETERS: Mapping[ReasonCode, Mapping[str, str]] = {
    code: _parameters(template) for code, template in TEMPLATES.items()
}


def catalog() -> dict[str, dict[str, str]]:
    """The codes with their parameters and kinds, as the OpenAPI document lists them."""
    return {code.value: dict(PARAMETERS[code]) for code in ReasonCode}


@dataclass(frozen=True)
class Reason:
    """A reason with its code: `params` are exactly the template's parameters; `subject` the
    name of the custom field it is about, `rule` the name of the rule it comes from, `field`
    the built-in check field (`contact`, ...) a node's reason is about."""

    code: ReasonCode
    params: Mapping[str, JsonValue] = field(default_factory=dict)
    subject: str | None = None
    rule: str | None = None
    field: str | None = None

    def __post_init__(self) -> None:
        expected = PARAMETERS[self.code].keys()
        if set(self.params) != set(expected):
            raise ValidationError(
                f"reason {self.code}: parameters {sorted(self.params)}, expected {sorted(expected)}"
            )

    def __hash__(self) -> int:
        params = json.dumps(self.params, sort_keys=True, ensure_ascii=False, default=str)
        return hash((self.code, params, self.subject, self.rule, self.field))

    @property
    def text(self) -> str:
        """In English, as the API and the log give it."""
        text = _FORMATTER.vformat(TEMPLATES[self.code], (), dict(self.params))
        if self.subject is not None:
            text = f"'{self.subject}': {text}"
        if self.rule is not None:
            text = f"rule '{self.rule}': {text}"
        if self.field is not None:
            text = f"{self.field}: {text}"
        return text

    def about(self, subject: str) -> Self:
        return replace(self, subject=subject)

    def by_rule(self, rule: str) -> Self:
        return replace(self, rule=rule)

    def for_field(self, field: str) -> Self:
        return replace(self, field=field)

    def to_json(self) -> JsonObject:
        data: JsonObject = {"code": self.code.value, "params": dict(self.params)}
        if self.subject is not None:
            data["subject"] = self.subject
        if self.rule is not None:
            data["rule"] = self.rule
        if self.field is not None:
            data["field"] = self.field
        return data

    @classmethod
    def from_json(cls, data: JsonValue) -> Self:
        """ValidationError for an unknown code (written by a newer version) or parameters that
        do not fit."""
        found = as_object(data)
        if found is None:
            raise ValidationError(f"invalid reason {data!r}")
        try:
            code = ReasonCode(str(found.get("code")))
        except ValueError:
            raise ValidationError(f"unknown reason code {found.get('code')!r}") from None
        return cls(
            code,
            dict(as_object(found.get("params")) or {}),
            subject=as_text(found.get("subject")),
            rule=as_text(found.get("rule")),
            field=as_text(found.get("field")),
        )


def because(code: ReasonCode, /, **params: object) -> Reason:
    """The reason `code` with `params` (JSON values; a tuple becomes a list)."""
    return Reason(code, {name: _json(value) for name, value in params.items()})


def _json(value: object) -> JsonValue:
    match value:
        case None | bool() | int() | float() | str():
            return value
        case list() | tuple():
            return [_json(item) for item in value]
        case dict():
            return {str(key): _json(item) for key, item in value.items()}
    raise TypeError(f"a reason's parameter is no JSON value: {value!r}")


def written(text: str) -> Reason:
    """A reason as written (`TEXT`)."""
    return Reason(ReasonCode.TEXT, {"text": text})


def text_of(reasons: Iterable[Reason]) -> str | None:
    """The reasons in English, joined by "; "; None without any."""
    return "; ".join(reason.text for reason in reasons) or None


def reasons_to_json(reasons: Iterable[Reason]) -> list[JsonValue]:
    return [reason.to_json() for reason in reasons]


def reasons_from_json(data: JsonValue, text: str | None) -> tuple[Reason, ...]:
    """The reasons stored next to their English `text`: as written where there are none (stored
    before reasons had codes) or they cannot be read (a code of a newer version)."""
    if isinstance(data, list):
        try:
            return tuple(Reason.from_json(item) for item in data)
        except ValidationError:
            pass
    return () if not text else (written(text),)
