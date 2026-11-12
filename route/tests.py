from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from route.service import _geocode_single_intersection, detect_issuing_state


@override_settings(GOOGLE_MAP_API_KEY="test-key")
class StateBoundedGeocodingTests(SimpleTestCase):
    def _response(self, state_code, lat, lng):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "status": "OK",
            "results": [{
                "address_components": [{
                    "short_name": state_code,
                    "long_name": state_code,
                    "types": ["administrative_area_level_1"],
                }],
                "geometry": {"location": {"lat": lat, "lng": lng}},
            }],
        }
        return response

    def test_issuing_state_header_wins_over_border_destination(self):
        text = "Nebraska Department of Transportation permit from Lincoln to Iowa state line"
        self.assertEqual(detect_issuing_state({}, text), "NE")

    @patch("route.service.AIExtractResponse.objects.create")
    @patch("route.service.requests.get")
    def test_nebraska_query_rejects_iowa_result(self, mocked_get, _mocked_log):
        mocked_get.return_value = self._response("IA", 41.5, -93.6)

        result = _geocode_single_intersection(
            "US-77 Junction",
            None,
            None,
            None,
            state_code="NE",
        )

        self.assertIsNone(result)
        self.assertTrue(mocked_get.called)
        self.assertEqual(
            mocked_get.call_args.kwargs["params"]["components"],
            "country:US|administrative_area:NE",
        )

    @patch("route.service.AIExtractResponse.objects.create")
    @patch("route.service.requests.get")
    def test_nebraska_query_accepts_nebraska_result(self, mocked_get, _mocked_log):
        mocked_get.return_value = self._response("NE", 41.12, -96.53)

        result = _geocode_single_intersection(
            "US-77 Junction",
            None,
            None,
            None,
            state_code="NE",
        )

        self.assertEqual(result["lat"], 41.12)
        self.assertEqual(result["lng"], -96.53)
