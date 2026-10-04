// Diagnostic fixtures, not captured Cloud responses or a proposed repair.
// Append to remote/client.rs in a disposable exact-source LanceDB checkout.
#[cfg(test)]
mod scout_http_error_boundary {
    use super::{test_utils::client_with_handler, Error};

    async fn assert_http(status: u16, body: &'static str) {
        let client = client_with_handler(|_| {
            http::Response::builder().status(200).body("").unwrap()
        });
        let response = http::Response::builder()
            .status(status)
            .body(body)
            .unwrap();
        let error = client
            .check_response("scout-preserved-request", response.into())
            .await
            .unwrap_err();
        match error {
            Error::Http {
                request_id,
                status_code,
                source,
            } => {
                assert_eq!(request_id, "scout-preserved-request");
                assert_eq!(status_code.unwrap().as_u16(), status);
                assert!(source.to_string().contains(body));
            }
            other => panic!("Unexpected classification: {other:?}"),
        }
    }

    #[tokio::test]
    async fn code13_invalid_input_is_http() {
        assert_http(
            400,
            r#"{"code":13,"error":"Bad request: InvalidArgument: Invalid input, vector dimension mismatch"}"#,
        )
        .await;
    }

    #[tokio::test]
    async fn same_code13_ref_conflict_is_http() {
        assert_http(
            400,
            r#"{"code":13,"error":"Bad request: InvalidArgument: Ref conflict error: tag already exists"}"#,
        )
        .await;
    }

    #[tokio::test]
    async fn unstructured400_is_preserved() {
        assert_http(400, "not a JSON error envelope").await;
    }

    #[tokio::test]
    async fn status_is_not_inferred_from_error_words() {
        for status in [403, 500] {
            assert_http(status, r#"{"code":13,"error":"Invalid input"}"#).await;
        }
    }
}
