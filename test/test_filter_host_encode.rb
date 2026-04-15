require_relative 'helper'
require 'tempfile'

class HostEncodeFilterTest < Test::Unit::TestCase
  setup do
    Fluent::Test.setup
    @patterns_file = Tempfile.new(['patterns', '.txt'])
    @patterns_file.write("10.0.*.1\n192.168.1.*\n# comment line\n\n")
    @patterns_file.close
  end

  teardown do
    @patterns_file.unlink
  end

  def run_filter(config, record)
    driver = Fluent::Test::Driver::Filter
      .new(Fluent::Plugin::HostEncodeFilter)
      .configure(config)
    driver.run(default_tag: 'test') do
      driver.feed(event_time, record)
    end
    driver.filtered_records.first
  end

  def base_config
    %(
      patterns_file #{@patterns_file.path}
      encode_fields host,message,ident
    )
  end

  sub_test_case '#configure' do
    test 'パターンファイルが正しく読み込まれる(コメント・空行除外)' do
      driver = Fluent::Test::Driver::Filter
        .new(Fluent::Plugin::HostEncodeFilter)
        .configure(base_config)
      patterns = driver.instance.instance_variable_get(:@patterns)
      assert_equal 2, patterns.size
    end

    test 'パターンファイルが無い場合 ConfigError' do
      assert_raise(Fluent::ConfigError) do
        Fluent::Test::Driver::Filter
          .new(Fluent::Plugin::HostEncodeFilter)
          .configure('patterns_file /nonexistent/file.txt')
      end
    end
  end

  sub_test_case '#filter' do
    test 'マッチするIPからのレコードは指定フィールドが変換される' do
      euc_text = 'こんにちは'.encode('EUC-JP')
      record = run_filter(base_config, {
        'host' => '10.0.5.1',
        'message' => euc_text,
        'ident' => euc_text
      })

      assert_equal 'こんにちは', record['message']
      assert_equal Encoding::UTF_8, record['message'].encoding
      assert_equal Encoding::UTF_8, record['ident'].encoding
    end

    test 'マッチしないIPはスルーされる' do
      euc_text = 'こんにちは'.encode('EUC-JP')
      record = run_filter(base_config, {
        'host' => '172.16.0.1',
        'message' => euc_text
      })

      assert_equal Encoding::EUC_JP, record['message'].encoding
    end

    test '変換不能バイトは置換文字で置き換わる' do
      invalid_bytes = "\xFF\xFE".force_encoding('EUC-JP')
      record = run_filter(base_config, {
        'host' => '10.0.5.1',
        'message' => invalid_bytes
      })

      assert_include record['message'], '?'
    end

    test 'encode_fields に指定していないフィールドは変換されない' do
      euc_text = 'こんにちは'.encode('EUC-JP')
      record = run_filter(base_config, {
        'host' => '10.0.5.1',
        'message' => euc_text,
        'other_field' => euc_text
      })

      assert_equal Encoding::UTF_8,  record['message'].encoding
      assert_equal Encoding::EUC_JP, record['other_field'].encoding
    end

    test 'ワイルドカードが正しく展開される' do
      euc_text = 'テスト'.encode('EUC-JP')
      record = run_filter(base_config, {
        'host' => '10.0.99.1',
        'message' => euc_text
      })
      assert_equal 'テスト', record['message']
    end

    test '対象フィールドが nil でもエラーにならない' do
      record = run_filter(base_config, {
        'host' => '10.0.5.1',
        'message' => nil
      })
      # nilのままか、変換が走らないことを確認
      assert_nil record['message']
    end
  end
end