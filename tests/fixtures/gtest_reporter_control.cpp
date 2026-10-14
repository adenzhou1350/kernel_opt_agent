
#include <gtest/gtest.h>
#include <string>
TEST(Report, Pass) { EXPECT_EQ(1, 1); }
TEST(Report, FailTwice) { EXPECT_EQ(1, 2); EXPECT_EQ(3, 4); }
TEST(Report, Skip) { GTEST_SKIP() << "deliberate skip"; }
TEST(Report, DISABLED_NotRun) { FAIL() << "must not run"; }
class SetupFailure : public ::testing::Test {
 protected:
  static void SetUpTestSuite() { FAIL() << "suite setup failure"; }
};
TEST_F(SetupFailure, Body) { SUCCEED(); }
class BadEnvironment : public ::testing::Environment {
 public:
  void SetUp() override { FAIL() << "global setup failure"; }
};
int main(int argc, char** argv) {
  for (int i = 1; i < argc; ++i)
    if (std::string(argv[i]) == "--environment-failure")
      ::testing::AddGlobalTestEnvironment(new BadEnvironment);
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
