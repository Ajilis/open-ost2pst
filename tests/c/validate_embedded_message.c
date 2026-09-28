#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <libpff.h>

static int fail(const char *message)
{
    fprintf(stderr, "%s\n", message);
    return EXIT_FAILURE;
}

int main(int argc, char **argv)
{
    libpff_file_t *file = NULL;
    libpff_item_t *ipm = NULL;
    libpff_item_t *inbox = NULL;
    libpff_item_t *message = NULL;
    libpff_item_t *attachment = NULL;
    libpff_item_t *embedded = NULL;
    libpff_error_t *error = NULL;
    uint8_t *subject = NULL;
    size_t subject_size = 0;
    int result = EXIT_FAILURE;
    int close_result = 0;

    if (argc != 2)
        return fail("usage: validate_embedded_message <pst>");

    if (libpff_file_initialize(&file, &error) != 1)
        goto cleanup;

    if (libpff_file_open(file, argv[1], LIBPFF_OPEN_READ, &error) != 1)
        goto cleanup;

    if (libpff_file_get_item_by_identifier(file, 0x8022, &ipm, &error) != 1)
        goto cleanup;

    /* Generated fixture order: Deleted Items, then Inbox. */
    if (libpff_folder_get_sub_folder(ipm, 1, &inbox, &error) != 1)
        goto cleanup;

    if (libpff_folder_get_sub_message(inbox, 0, &message, &error) != 1)
        goto cleanup;

    if (libpff_message_get_attachment(message, 0, &attachment, &error) != 1)
        goto cleanup;

    if (libpff_attachment_get_item(attachment, &embedded, &error) != 1)
        goto cleanup;

    if (embedded == NULL)
        goto cleanup;

    if (libpff_message_get_utf8_subject_size(
            embedded,
            &subject_size,
            &error) != 1)
        goto cleanup;

    subject = (uint8_t *) malloc(subject_size);
    if (subject == NULL)
        goto cleanup;

    if (libpff_message_get_utf8_subject(
            embedded,
            subject,
            subject_size,
            &error) != 1)
        goto cleanup;

    if (strcmp((const char *) subject, "Embedded subject") != 0)
        goto cleanup;

    printf("embedded-message subject: %s\n", subject);
    result = EXIT_SUCCESS;

cleanup:
    free(subject);

    if (embedded != NULL)
        libpff_item_free(&embedded, NULL);
    if (attachment != NULL)
        libpff_item_free(&attachment, NULL);
    if (message != NULL)
        libpff_item_free(&message, NULL);
    if (inbox != NULL)
        libpff_item_free(&inbox, NULL);
    if (ipm != NULL)
        libpff_item_free(&ipm, NULL);

    if (file != NULL) {
        close_result = libpff_file_close(file, NULL);
        (void) close_result;
        libpff_file_free(&file, NULL);
    }

    if (error != NULL)
        libpff_error_free(&error);

    if (result != EXIT_SUCCESS)
        fprintf(stderr, "libpff_attachment_get_item validation failed\n");

    return result;
}
